"""Jarvis's slow, careful thinking for detailed questions.

The quick brain hands detailed questions here and the conversation carries on. A background
thread works through them one at a time with the bigger model (thinking switched on, web
search allowed). When an answer is ready Jarvis asks before speaking:
  yes  -> it tells you
  wait -> it holds the answer and offers it again later
  no   -> it stays quiet, but the answer is kept in long-term memory
"""

import queue
import threading
import time
import uuid

import ollama

import config
import pc_tools

SYSTEM = """You are J.A.R.V.I.S., thinking carefully in the background about a detailed \
question from the user. Use web_search when you need facts, figures or anything recent. \
Then write your answer to be spoken aloud: clear and well organised, about four to eight \
sentences, plain words, no markdown, bullet symbols or emoji. Start with the direct answer, \
then the key reasons or steps."""

RESEARCH_TOOLS = {f.__name__: f for f in (pc_tools.web_search, pc_tools.get_weather)}
HOLD_SECONDS = 180  # after "wait", offer the answer again this much later


class DeepThinker:
    def __init__(self, bus, memory):
        self.bus = bus
        self.memory = memory
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.tasks: dict[str, dict] = {}
        self._queue: queue.Queue[dict] = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, question: str, context: list[dict]) -> dict:
        task = {
            "id": uuid.uuid4().hex[:8], "question": question, "status": "queued",
            "thinking": "", "answer": "", "created": time.time(), "_context": context, "_offer_after": 0.0,
        }
        with self._lock:
            self.tasks[task["id"]] = task
        self.bus.task(task)
        self._queue.put(task)
        return task

    def next_to_offer(self) -> dict | None:
        """A finished answer Jarvis should now ask about, if any."""
        now = time.time()
        with self._lock:
            for task in self.tasks.values():
                if task["status"] in ("ready", "held") and task["_offer_after"] <= now:
                    return task
        return None

    def get(self, task_id: str) -> dict | None:
        return self.tasks.get(task_id)

    def decide(self, task: dict, choice: str):
        status = {"yes": "told", "wait": "held", "no": "declined"}[choice]
        task["status"] = status
        if choice == "wait":
            task["_offer_after"] = time.time() + HOLD_SECONDS
        if task.get("_memory_id"):
            self.memory.update(task["_memory_id"], status=status)
        self.bus.task(task)

    # ----- background work -----

    def _worker(self):
        while True:
            task = self._queue.get()
            try:
                self._think(task)
            except Exception as e:
                task["status"] = "failed"
                task["answer"] = f"I couldn't finish thinking about that: {e}"
                self.bus.task(task)

    def _think(self, task: dict):
        task["status"] = "thinking"
        self.bus.task(task)
        messages = [
            {"role": "system", "content": SYSTEM},
            *task["_context"],
            {"role": "user", "content": task["question"]},
        ]
        answer = ""
        for _ in range(4):  # a few rounds of research at most
            content, tool_calls = self._stream(task, messages)
            if not tool_calls:
                answer = content
                break
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for call in tool_calls:
                tool = RESEARCH_TOOLS.get(call.function.name)
                try:
                    result = str(tool(**call.function.arguments)) if tool else "No such tool."
                except Exception as e:
                    result = f"Error: {e}"
                self._note(task, f"\n[{call.function.name}: {call.function.arguments}]\n")
                messages.append({"role": "tool", "content": result, "tool_name": call.function.name})

        if not answer.strip():
            # Ran out of room while still thinking: ask for the answer from the notes so far.
            messages.append({"role": "user", "content": "Give your spoken answer now, from what you have worked out."})
            answer = self._stream(task, messages, think=False)[0]

        task["answer"] = answer.strip() or "I'm afraid I couldn't reach a good answer."
        task["status"] = "ready"
        task["_memory_id"] = self.memory.add("answer", task["answer"], question=task["question"], status="ready")["id"]
        self.bus.task(task)

    def _stream(self, task: dict, messages: list, think: bool = True):
        content, tool_calls, last_update = "", [], 0.0
        for part in self.client.chat(
            model=config.DEEP_MODEL, messages=messages, tools=list(RESEARCH_TOOLS.values()),
            think=think, stream=True, keep_alive="3m",  # unload soon after, to give memory back
            options={"num_ctx": 8192, "num_predict": 1800},
        ):
            message = part.message
            if message.thinking:
                task["thinking"] += message.thinking
            if message.content:
                content += message.content
            if message.tool_calls:
                tool_calls.extend(message.tool_calls)
            if time.time() - last_update > 0.5:  # live thinking on the website, twice a second
                last_update = time.time()
                self.bus.task(task)
        return content, tool_calls

    def _note(self, task: dict, text: str):
        task["thinking"] += text
        self.bus.task(task)

