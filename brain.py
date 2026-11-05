"""Jarvis's quick brain: a small, fast AI model running on this PC through Ollama.

It answers simple things straight away, uses the PC tools, and hands detailed questions
to the deep thinker (deep.py) so the conversation can carry on meanwhile.
"""

import datetime
import re
import threading

import ollama

import config
import pc_tools

SYSTEM = f"""You are J.A.R.V.I.S., a personal AI assistant running on the user's Windows PC, \
modelled on the assistant from the Iron Man films: calm, capable, with a dry British wit. \
The user is not Tony Stark; never call them Mr. Stark or Tony.

Everything you write is spoken aloud, so talk like a person: one or two short sentences, \
plain words. Never use markdown, bullet points, emoji, or read out web addresses. Don't end \
with offers or follow-up questions unless you truly need an answer.

{f'Address the user as "{config.CALL_ME}" now and then.' if config.CALL_ME else ''}

Tools:
- Detailed questions that need explanation, advice, planning, comparison or several steps: \
think_deeply. Quick facts and chat: answer yourself.
- Weather: get_weather.
- Facts, people, films, news, prices or scores you can't answer with certainty: call \
web_search right away. Never say you don't know and never offer to search; just search. \
Answer only with facts stated in the results; if they don't say, admit it.
- Apps, websites, music, volume, timers, PC status, locking: always call the matching tool. \
Never claim you did something without calling its tool.
- "Remember that...": remember. Questions about earlier conversations or answers you \
prepared before: recall.
Only do what the latest message asks. Never repeat earlier actions or add extra ones \
(for example, don't change the volume unless asked).

Each user message starts with the local date and time in brackets; use it when relevant."""

# Tools whose result already says what happened, so Jarvis can speak it without asking the AI
# to write a reply (saves several seconds).
ACTION_TOOLS = {
    "open_app", "open_website", "set_volume", "media_control", "set_timer", "lock_computer",
    "think_deeply", "remember",
}
# Conversation memory, in messages. When it passes MAX_HISTORY, trim it down to KEEP_HISTORY.
# Trimming in big, rare steps matters: Ollama reuses its work on an unchanged conversation
# start, and every trim forces it to re-read everything (10+ seconds on a laptop).
MAX_HISTORY = 40
KEEP_HISTORY = 16


USER_WORDS = [
    (r"\bI am\b|\bI'm\b", "the user is"), (r"\bI've\b|\bI have\b", "the user has"), (r"\bmy\b", "the user's"),
    (r"\bmine\b", "the user's"), (r"\bme\b", "the user"), (r"\bI\b", "the user"),
]


def about_user(fact: str) -> str:
    """'my exam is Monday' -> "the user's exam is Monday", so the model doesn't think it's about itself."""
    for pattern, replacement in USER_WORDS:
        fact = re.sub(pattern, replacement, fact, flags=re.IGNORECASE)
    return fact[0].upper() + fact[1:] if fact else fact


def clean_reply(text: str) -> str:
    # Some models still write out their reasoning; never speak it.
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


class Brain:
    def __init__(self, deep=None, memory=None, on_tool=lambda name, args, result: None):
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.messages: list = []
        self.deep = deep
        self.memory = memory
        self.on_tool = on_tool
        self.tools = {tool.__name__: tool for tool in pc_tools.ALL_TOOLS}
        if deep:
            self.tools["think_deeply"] = self.think_deeply
        if memory:
            self.tools["remember"] = self.remember
            self.tools["recall"] = self.recall
        self.system = SYSTEM
        facts = memory.facts() if memory else []
        if facts:
            # Fixed for the whole session, so Ollama can keep reusing its work on the prompt.
            self.system += "\n\nThings you remember about the user:\n" + "\n".join(f"- {f}" for f in facts)

    # ----- tools that use Jarvis's own parts -----

    def think_deeply(self, question: str) -> str:
        """Hand a detailed question to your slower, careful thinking. Use it for anything that needs
        explanation, advice, planning, comparison, step-by-step reasoning or many facts. It works in the
        background while you keep talking, and you'll ask the user before sharing the answer.

        Args:
            question: The full question, including any details the user gave.
        """
        self.deep.submit(question, self.recent_context())
        return "Let me think that through properly. Carry on; I'll let you know when I'm ready."

    def remember(self, fact: str) -> str:
        """Save something to long-term memory: the user's preferences, plans, or facts about them.

        Args:
            fact: What to remember, as a short sentence, e.g. "The user's exam is on 12 December."
        """
        self.memory.add("fact", about_user(fact))
        return "I'll remember that."

    def recall(self, topic: str) -> str:
        """Search long-term memory: things the user asked you to remember, and detailed answers you
        prepared earlier, including ones the user held back or declined to hear.

        Args:
            topic: What to look for, e.g. "exam" or "trip to Japan".
        """
        found = self.memory.search(topic)
        if not found:
            return "Nothing in memory about that."
        lines = []
        for item in found:
            if item["kind"] == "answer":
                lines.append(f"Earlier answer ({item['time']}) to \"{item['question']}\": {item['text']}")
            else:
                lines.append(f"Remembered ({item['time']}): {item['text']}")
        return "\n".join(lines)

    # ----- talking -----

    def setup(self):
        """Make sure Ollama is running and the models are downloaded. Raises ConnectionError if not."""
        installed = {m.model for m in self.client.list().models}
        for model in dict.fromkeys([config.OLLAMA_MODEL, config.DEEP_MODEL if self.deep else config.OLLAMA_MODEL]):
            if model in installed:
                continue
            print(f"Downloading the AI model {model} (one time, a few GB)...")
            last = ""
            for progress in self.client.pull(model, stream=True):
                if progress.total and progress.completed:
                    line = f"  {progress.status}: {100 * progress.completed / progress.total:.0f}%"
                    if line != last:
                        print(line, end="\r")
                        last = line
            print()
        # Load the model and pre-read the instructions in the background, so the first reply is quicker.
        threading.Thread(target=self._warm_up, daemon=True).start()

    def _warm_up(self):
        try:
            self._chat([{"role": "user", "content": "Hello"}], num_predict=1)
        except Exception:
            pass

    def _chat(self, messages: list, **options):
        return self.client.chat(
            model=config.OLLAMA_MODEL,
            messages=[{"role": "system", "content": self.system}, *messages],
            tools=list(self.tools.values()),
            think=False,  # skip slow step-by-step reasoning; quick answers suit a voice assistant
            options={"num_ctx": 6144, "num_predict": 200, **options},
            keep_alive="1h",
        )

    def ask(self, text: str) -> str:
        now = datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")
        self._forget_old()
        turn_start = len(self.messages)
        content = f"[{now}] {text}"
        # Small models overlook facts buried in the instructions, so attach matching ones right here.
        facts = [i["text"] for i in self.memory.search(text) if i["kind"] == "fact"] if self.memory else []
        if facts:
            content += "\n(From your long-term memory: " + " ".join(facts) + ")"
        self.messages.append({"role": "user", "content": content})
        try:
            return self._run()
        except Exception:
            # Drop the half-finished turn so the conversation stays valid.
            del self.messages[turn_start:]
            raise

    def use_tool_now(self, name: str, arguments: dict, text: str) -> str:
        """Run a tool directly, skipping the AI (when the user's words make the intent obvious)."""
        reply = self.run_tool(name, arguments)
        self.messages += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        return reply

    def recent_context(self, turns: int = 6) -> list[dict]:
        """The last few plain exchanges, so deep thinking knows what you were talking about."""
        plain = [
            {"role": m["role"], "content": m["content"]}
            for m in self.messages
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
        ]
        return plain[-turns:]

    def run_tool(self, name: str, arguments: dict) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"Error: there is no tool called {name}."
        try:
            result = str(tool(**arguments))
        except Exception as e:
            result = f"Error running {name}: {e}"
        self.on_tool(name, arguments, result)
        return result

    def _run(self) -> str:
        for _ in range(4):  # at most 4 rounds of tool use per question
            message = self._chat(self.messages).message
            self.messages.append(message)
            if not message.tool_calls:
                reply = clean_reply(message.content) or "Done."
                return reply
            results = []
            for call in message.tool_calls:
                result = self.run_tool(call.function.name, call.function.arguments)
                print(f"  [{call.function.name}] {result[:100]}")
                results.append(result)
                self.messages.append({"role": "tool", "content": result, "tool_name": call.function.name})
            # Stop right after actions: faster, and small models otherwise tend to tack on
            # extra actions nobody asked for (like changing the volume).
            if all(call.function.name in ACTION_TOOLS for call in message.tool_calls):
                reply = " ".join(results)
                self.messages.append({"role": "assistant", "content": reply})
                return reply
        return "I'm afraid I got a bit tangled up with that one."

    def _forget_old(self):
        """Keep the conversation short, starting at a question so no tool result is cut in half."""
        if len(self.messages) <= MAX_HISTORY:
            return
        starts = [i for i, m in enumerate(self.messages) if isinstance(m, dict) and m.get("role") == "user"]
        cut = next((i for i in starts if len(self.messages) - i <= KEEP_HISTORY), starts[-1])
        del self.messages[:cut]
