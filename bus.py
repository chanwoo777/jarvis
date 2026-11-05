"""Live link between Jarvis and its website.

A small server on this PC (port 8765, reachable only from this PC) that:
- serves the website itself at http://localhost:8765, and
- lets the website connect over a WebSocket at /ws to watch what Jarvis hears, thinks
  and does, and to send typed messages, "listen" presses and Yes/Wait/No decisions.

Only Jarvis's own website (GitHub Pages or localhost) may connect, and only with the
pairing code Jarvis makes fresh at every start, so other websites can't control your PC.
"""

import asyncio
import json
import mimetypes
import os
import queue
import re
import secrets
import threading
import time
from collections import deque

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

import config

WEB_DIR = (config.ROOT / "docs").resolve()
ALLOWED_ORIGINS = [config.WEBSITE_ORIGIN, re.compile(r"http://(localhost|127\.0\.0\.1)(:\d+)?"), None]
COMMANDS = {"say", "listen", "decide"}
# A small "tick" this often lets the page notice a dead connection and reconnect by itself.
HEARTBEAT_SECONDS = 15
# A page this far behind (e.g. frozen by Chrome) is disconnected; it resyncs when it comes back.
MAX_BACKLOG = 500


class Bus:
    def __init__(self):
        # The launcher passes the code it gave the website; otherwise make a fresh one.
        self.token = os.environ.get("JARVIS_TOKEN") or secrets.token_urlsafe(12)
        self.inbox: queue.Queue[dict] = queue.Queue()  # commands from the website
        self.state = "starting"
        self.info: dict = {}
        self.history: deque[dict] = deque(maxlen=60)  # recent messages and actions, for newly opened pages
        self.tasks: dict[str, dict] = {}
        self.memory: list[dict] = []
        # Each open page's outbox, and whether that page is visible. Hidden pages get no mic-level
        # updates: a background tab receiving 12 messages a second looks busy to Chrome, which then
        # freezes or unloads it after a few minutes and drops the connection.
        self._clients: dict[asyncio.Queue, dict] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._last_level = 0.0

    # ----- server -----

    def start(self) -> bool:
        """Start the server in the background. False if it couldn't (e.g. the port is in use)."""
        ready = threading.Event()
        threading.Thread(target=lambda: asyncio.run(self._serve(ready)), daemon=True).start()
        return ready.wait(5)

    async def _serve(self, ready: threading.Event):
        self._loop = asyncio.get_running_loop()
        async with serve(self._handle, "127.0.0.1", config.PORT, origins=ALLOWED_ORIGINS, process_request=self._http):
            ready.set()
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                self._send({"type": "tick"})

    def _http(self, connection, request):
        """Serve the website's files for anything that isn't the WebSocket."""
        path = request.path.split("?")[0]
        if path == "/ws":
            return None
        file = (WEB_DIR / (path.lstrip("/") or "index.html")).resolve()
        if file.is_dir():
            file = file / "index.html"
        if not file.is_relative_to(WEB_DIR) or not file.is_file():
            return connection.respond(404, "Not found\n")
        body = file.read_bytes()
        kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        headers = Headers([("Content-Type", kind), ("Content-Length", str(len(body))), ("Cache-Control", "no-cache")])
        return Response(200, "OK", headers, body)

    async def _handle(self, ws):
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        except Exception:
            return
        if hello.get("type") != "auth" or not secrets.compare_digest(str(hello.get("token", "")), self.token):
            await ws.send(json.dumps({"type": "auth_failed"}))
            return

        outbox: asyncio.Queue = asyncio.Queue()
        client = {"visible": True}
        with self._lock:
            self._clients[outbox] = client
            snapshot = self._snapshot()
        await ws.send(json.dumps(snapshot))

        async def pump():
            while True:
                if outbox.qsize() > MAX_BACKLOG:
                    await ws.close(1013, "page fell behind; reconnect to resync")
                    return
                await ws.send(await outbox.get())

        sender = asyncio.create_task(pump())
        connected_at = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] Website connected")
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("type") == "view":
                    client["visible"] = bool(msg.get("visible"))
                elif msg.get("type") in COMMANDS:
                    self.inbox.put(msg)
        except Exception:
            pass
        finally:
            sender.cancel()
            with self._lock:
                self._clients.pop(outbox, None)
            print(
                f"[{time.strftime('%H:%M:%S')}] Website disconnected after {time.time() - connected_at:.0f}s "
                f"(code {ws.close_code}, {ws.close_reason or 'no reason given'}; {outbox.qsize()} messages unsent)"
            )

    def _snapshot(self) -> dict:
        return {
            "type": "snapshot", "info": self.info, "state": self.state,
            "history": list(self.history), "tasks": list(self.tasks.values()), "memory": self.memory,
        }

    def _send(self, event: dict, visible_only: bool = False):
        if self._loop is None:
            return
        data = json.dumps(event)
        with self._lock:
            clients = [q for q, c in self._clients.items() if c["visible"] or not visible_only]
        for outbox in clients:
            self._loop.call_soon_threadsafe(outbox.put_nowait, data)

    @property
    def connected(self) -> bool:
        return bool(self._clients)

    def pair_urls(self) -> tuple[str, str]:
        return f"{config.WEBSITE_URL}#pair={self.token}", f"http://localhost:{config.PORT}/#pair={self.token}"

    # ----- events Jarvis sends -----

    def set_info(self, **info):
        self.info.update(info)
        self._send({"type": "info", "info": self.info})

    def set_state(self, state: str):
        """idle, listening, thinking, speaking or asking."""
        if state != self.state:
            self.state = state
            self._send({"type": "state", "state": state})

    def level(self, rms: float):
        """Microphone loudness, so the orb can react to your voice (at most 12 updates a second)."""
        now = time.time()
        if self._clients and now - self._last_level > 0.08:
            self._last_level = now
            self._send({"type": "level", "value": round(min(1.0, rms / 3000), 3)}, visible_only=True)

    def message(self, role: str, text: str, via: str = ""):
        event = {"type": "message", "role": role, "text": text, "via": via, "time": time.time()}
        self.history.append(event)
        self._send(event)

    def action(self, tool: str, args: dict, result: str):
        event = {"type": "action", "tool": tool, "args": args, "result": result, "time": time.time()}
        self.history.append(event)
        self._send(event)

    def task(self, task: dict):
        public = {k: v for k, v in task.items() if not k.startswith("_")}
        public["thinking"] = public.get("thinking", "")[-1500:]  # the page only needs the latest part
        self.tasks[task["id"]] = public
        self._send({"type": "task", "task": public})

    def set_memory(self, items: list[dict]):
        self.memory = items[-30:]
        self._send({"type": "memory", "items": self.memory})

    def error(self, text: str):
        self._send({"type": "error", "text": text})
