"""Jarvis's long-term memory, kept in a private GitHub repo instead of on this PC's disk.

Memories are held in RAM while Jarvis runs and saved to memory.json in the repo a couple of
seconds after each change (in the background, so talking never waits for it). Nothing is
written to the local disk. You can read or edit the memories on github.com.

Access uses the GitHub CLI's login (`gh auth token`), which Windows keeps in its credential store.
"""

import base64
import json
import re
import subprocess
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://api.github.com"
FILE = "memory.json"
# Words too common to tell memories apart ("the user's ..." is in every fact).
STOPWORDS = set(
    "the user users you your yours what whats when where which who why how and are was were for "
    "that this these those with have has had about from can could would should did does doing "
    "tell know remember there their them they its it's not any all".split()
)


class Memory:
    def __init__(self, repo: str, on_change=lambda items: None):
        self.repo = repo  # "owner/name"; blank = only remember until Jarvis closes
        self.items: list[dict] = []
        self.on_change = on_change
        self.status = "session only" if not repo else "not loaded"
        self._sha: str | None = None
        self._token = ""
        self._loaded = False  # never save before reading what's already on GitHub, or it would be overwritten
        self._lock = threading.Lock()
        self._dirty = threading.Event()

    def load(self, attempts: int = 6):
        if not self.repo:
            return
        for attempt in range(attempts):  # right after login the network may not be up yet
            if self._fetch():
                break
            if attempt < attempts - 1:
                time.sleep(5)
        threading.Thread(target=self._saver, daemon=True).start()
        self.on_change(self.items)

    def _fetch(self) -> bool:
        """Read memory.json from GitHub. True once the saved memories are known."""
        try:
            self._token = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=20
            ).stdout.strip()
            data = self._api("GET", f"/repos/{self.repo}/contents/{FILE}")
            with self._lock:
                saved = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
                known = {i["id"] for i in saved}
                self.items = saved + [i for i in self.items if i["id"] not in known]
                self._sha = data["sha"]
            self.status = f"{len(self.items)} memories in github.com/{self.repo}"
        except HTTPError as e:
            if e.code != 404:
                self.status = f"GitHub error {e.code}; will keep trying"
                return False
            self.status = f"empty, saving to github.com/{self.repo}"  # no memories saved yet
        except (URLError, OSError, ValueError) as e:
            self.status = f"offline ({e}); will keep trying"
            return False
        self._loaded = True
        return True

    # ----- reading and writing -----

    def add(self, kind: str, text: str, **extra) -> dict:
        item = {"id": uuid.uuid4().hex[:8], "time": time.strftime("%Y-%m-%d %H:%M"), "kind": kind, "text": text, **extra}
        with self._lock:
            self.items.append(item)
        self._changed()
        return item

    def update(self, item_id: str, **fields):
        with self._lock:
            for item in self.items:
                if item["id"] == item_id:
                    item.update(fields)
        self._changed()

    def facts(self, limit: int = 15) -> list[str]:
        return [i["text"] for i in self.items if i["kind"] == "fact"][-limit:]

    def search(self, query: str, limit: int = 4) -> list[dict]:
        words = set(re.findall(r"\w{3,}", query.lower())) - STOPWORDS
        scored = []
        for n, item in enumerate(self.items):
            haystack = f"{item.get('question', '')} {item['text']}".lower()
            score = sum(w in haystack for w in words)
            if score or not words:
                scored.append((score, n, item))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)  # best match, then newest
        return [item for _, _, item in scored[:limit]]

    def _changed(self):
        self.on_change(self.items)
        self._dirty.set()

    # ----- saving to GitHub -----

    def _saver(self):
        while True:
            self._dirty.wait()
            time.sleep(2)  # bundle quick changes into one save
            self._dirty.clear()
            if not self.repo:
                continue
            try:
                if not self._loaded and not self._fetch():
                    raise ConnectionError(self.status)
                self._save()
            except Exception as e:
                print(f"(memory: couldn't save to GitHub: {e}; will retry)")
                time.sleep(30)
                self._dirty.set()

    def _save(self):
        with self._lock:
            content = json.dumps(self.items, ensure_ascii=False, indent=1).encode("utf-8")
        body = {"message": "Jarvis memory update", "content": base64.b64encode(content).decode()}
        if self._sha:
            body["sha"] = self._sha
        try:
            result = self._api("PUT", f"/repos/{self.repo}/contents/{FILE}", body)
        except HTTPError as e:
            if e.code not in (409, 422):
                raise
            # Our copy of the file's version is stale; fetch the current one and retry.
            self._sha = self._api("GET", f"/repos/{self.repo}/contents/{FILE}")["sha"]
            body["sha"] = self._sha
            result = self._api("PUT", f"/repos/{self.repo}/contents/{FILE}", body)
        self._sha = result["content"]["sha"]
        self.status = f"{len(self.items)} memories in github.com/{self.repo}"

    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        request = Request(
            API + path,
            method=method,
            data=json.dumps(body).encode() if body else None,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=20) as response:
            return json.load(response)
