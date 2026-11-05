"""Tiny helper that runs from Windows login so the Jarvis website can start Jarvis.

It listens on this PC only (127.0.0.1, port 8766), accepts only Jarvis's own website, and can do
exactly one thing: start Jarvis (minimized) and tell the website that run's pairing code. It uses
almost no memory while it waits.

    pythonw launcher.py           wait for the website
    pythonw launcher.py --start   also start Jarvis right away (used at login)
"""

import asyncio
import json
import os
import re
import secrets
import socket
import subprocess
import sys

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

import config

PORT = config.PORT + 1
ALLOWED_ORIGINS = [config.WEBSITE_ORIGIN, re.compile(r"http://(localhost|127\.0\.0\.1)(:\d+)?")]
token: str | None = None  # pairing code of the Jarvis this launcher started


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


async def code_works(code: str | None) -> bool:
    """Is this still the running Jarvis's pairing code? (Not if Jarvis was restarted another way.)"""
    if not code:
        return False
    try:
        async with connect(f"ws://127.0.0.1:{config.PORT}/ws", origin="http://127.0.0.1", open_timeout=3) as ws:
            await ws.send(json.dumps({"type": "auth", "token": code}))
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=3)).get("type") == "snapshot"
    except Exception:
        return False


def start_jarvis(open_website: bool):
    global token
    token = secrets.token_urlsafe(12)
    env = {**os.environ, "JARVIS_TOKEN": token, "JARVIS_OPEN_WEBSITE": "yes" if open_website else "no"}
    bat = config.ROOT / "run_jarvis.bat"
    subprocess.Popen(f'start "Jarvis" /min "{bat}"', shell=True, cwd=config.ROOT, env=env)


async def handle(ws):
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if msg.get("type") != "start":
            continue
        if port_open(config.PORT):
            # Already running. If Jarvis was started some other way, its code isn't known here.
            await ws.send(json.dumps({"type": "running", "token": token if await code_works(token) else None}))
        else:
            start_jarvis(open_website=False)  # the page asking is already open
            await ws.send(json.dumps({"type": "starting", "token": token}))


async def main():
    if port_open(PORT):
        return  # a launcher is already running
    if "--start" in sys.argv and not port_open(config.PORT):
        start_jarvis(open_website=True)
    async with serve(handle, "127.0.0.1", PORT, origins=ALLOWED_ORIGINS):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
