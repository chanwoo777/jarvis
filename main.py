"""Jarvis: say "Hey Jarvis", ask something, hear the answer. Watch it all on the website.

    python main.py             talk out loud
    python main.py --text      type instead (no microphone needed)
    python main.py --mute      print replies instead of speaking them
    python main.py --mic-test  check that Jarvis can hear you (no AI needed)
"""

import argparse
import re
import sys
import threading
import time
import webbrowser
from collections import deque

import ollama

import config
import pc_tools
from brain import Brain
from bus import Bus
from deep import DeepThinker
from memory import Memory
from voice import Voice

EXIT_PHRASES = {"shut down", "goodbye", "good bye", "exit", "quit", "go to sleep", "power down"}
# Phrases that clearly ask for careful thinking go straight to the deep thinker.
DEEP_REQUEST = re.compile(r"\b(think (about|deeply|carefully|it through|hard)|take your time|in detail|detailed|step by step)\b", re.I)
# "Remember that ..." is saved directly; the small model sometimes only pretends to.
REMEMBER = re.compile(r"^(?:jarvis,?\s*)?(?:please\s+)?(?:remember|don'?t forget)\s+(?:that\s+)?(.+)", re.I)
# Replies to "Shall I tell you now?" ("wait" is checked first: "not now" isn't a no).
WAIT = re.compile(r"\b(wait|later|hold|not now|not yet|hang on|in a (minute|moment|bit|second)|give me a)\b")
NO = re.compile(r"\b(no|nope|don'?t|never ?mind|skip)\b")
YES = re.compile(r"\b(yes|yeah|yep|yup|sure|go ahead|okay|ok|please|tell me|go on|alright|do it)\b")


def is_exit(text: str) -> bool:
    words = re.sub(r"[^a-z ]", "", text.lower()).replace("jarvis", "").replace("hey", "")
    return " ".join(words.split()) in EXIT_PHRASES


def parse_decision(text: str) -> str | None:
    text = text.lower()
    for choice, pattern in (("wait", WAIT), ("no", NO), ("yes", YES)):
        if pattern.search(text):
            return choice
    return None


def topic(question: str) -> str:
    words = question.split()
    short = " ".join(words[:10]) + ("..." if len(words) > 10 else "")
    return f'your question, "{short}"'


def think(brain: Brain, text: str) -> str:
    try:
        return brain.ask(text)
    except ConnectionError:
        return "I can't reach my brain. Please make sure the Ollama app is running."
    except ollama.ResponseError as e:
        print(f"(Ollama error: {e.error})")
        return "Something went wrong while I was thinking."


def greeting() -> str:
    return f"Jarvis online. At your service, {config.CALL_ME}." if config.CALL_ME else "Jarvis online."


class Jarvis:
    """Ties the parts together: what to do with each thing you say, type or click."""

    def __init__(self, voice: Voice, bus: Bus, brain: Brain, deep: DeepThinker, ears=None):
        self.voice, self.bus, self.brain, self.deep, self.ears = voice, bus, brain, deep, ears
        self.pending: deque[dict] = deque()  # commands from the website / console, not yet handled

    # ----- speaking and listening -----

    def say(self, text: str):
        print(f"Jarvis: {text}")
        self.bus.message("jarvis", text)
        self.bus.set_state("speaking")
        self.voice.say(text)
        if self.ears:
            self.ears.flush()  # don't let Jarvis hear itself
        self.bus.set_state("idle")

    def respond(self, text: str, via: str) -> bool:
        """Answer one thing the user said or typed. Returns False if they asked Jarvis to close."""
        print(f"You: {text}")
        self.bus.message("user", text, via)
        if is_exit(text):
            self.say("Goodbye.")
            return False
        self.bus.set_state("thinking")
        remember = REMEMBER.match(text)
        if remember and self.brain.memory:
            reply = self.brain.use_tool_now("remember", {"fact": remember.group(1).rstrip(".")}, text)
        elif DEEP_REQUEST.search(text):
            reply = self.brain.use_tool_now("think_deeply", {"question": text}, text)
        else:
            reply = think(self.brain, text)
        self.say(reply)
        return True

    def hear(self, stop=None, max_wait: float = 8.0) -> str | None:
        """Listen for one spoken reply without the wake word."""
        audio = self.ears.record(max_wait=max_wait, on_chunk=self.bus.level, interrupt=stop)
        return self.ears.transcribe(audio) if audio is not None else None

    def conversation(self) -> bool:
        """After "Hey Jarvis": keep talking without the wake word until you go quiet."""
        follow_up = False
        while True:
            self.bus.set_state("listening")
            text = self.hear(max_wait=5.0 if follow_up else 7.0)
            if not text:
                return True
            if not self.respond(text, "voice"):
                return False
            self.voice.beep_follow_up()
            follow_up = True

    # ----- finished deep answers: ask before speaking -----

    def offer(self) -> bool:
        task = self.deep.next_to_offer()
        if task is None:
            return True
        self.say(f"I've finished thinking about {topic(task['question'])}. Shall I tell you now?")
        task["asking"] = True
        self.bus.task(task)
        self.bus.set_state("asking")

        heard = self._wait_for_reply(lambda: self._take_decision(task["id"], peek=True))
        clicked = self._take_decision(task["id"])
        task["asking"] = False
        if clicked:
            return self.apply(task, clicked)
        via = "voice" if self.ears else "text"
        choice = parse_decision(heard) if heard else "wait"
        if choice is None:
            # They said something else entirely: hold the answer and deal with what they said.
            self.apply(task, "wait", quiet=True)
            return self.respond(heard, via)
        if heard:
            print(f"You: {heard}")
            self.bus.message("user", heard, via)
        return self.apply(task, choice)

    def apply(self, task: dict, choice: str, quiet: bool = False) -> bool:
        self.deep.decide(task, choice)
        if choice == "yes":
            self.say(task["answer"])
        elif not quiet:
            self.say("Alright, I'll hold onto it for later." if choice == "wait"
                     else "Understood. I'll keep it in my memory in case you want it later.")
        return True

    def _wait_for_reply(self, stop) -> str | None:
        if self.ears:
            return self.hear(stop=stop)
        # Text mode: wait up to 30 seconds for a typed reply.
        deadline = time.time() + 30
        while time.time() < deadline and not stop():
            self._pull()
            for msg in list(self.pending):
                if msg["type"] == "say":
                    self.pending.remove(msg)
                    return msg["text"]
            time.sleep(0.2)
        return None

    # ----- commands from the website (and the console in text mode) -----

    def _pull(self):
        while not self.bus.inbox.empty():
            self.pending.append(self.bus.inbox.get_nowait())

    def _take_decision(self, task_id: str, peek: bool = False) -> str | None:
        self._pull()
        for msg in self.pending:
            if msg["type"] == "decide" and msg.get("id") == task_id and msg.get("choice") in ("yes", "wait", "no"):
                if not peek:
                    self.pending.remove(msg)
                return msg["choice"]
        return None

    def has_work(self) -> bool:
        self._pull()
        return bool(self.pending) or self.deep.next_to_offer() is not None

    def handle_pending(self) -> bool:
        """Handle website/console commands, then any finished answers. False = close Jarvis."""
        while True:
            self._pull()
            if not self.pending:
                break
            msg = self.pending.popleft()
            if msg["type"] == "quit":
                return False
            if msg["type"] == "say" and str(msg.get("text", "")).strip():
                if not self.respond(str(msg["text"]).strip(), "text"):
                    return False
            elif msg["type"] == "listen" and self.ears:
                self.voice.beep_listening()
                if not self.conversation():
                    return False
                self.voice.beep_done()
            elif msg["type"] == "decide":
                task = self.deep.get(str(msg.get("id")))
                if task and msg.get("choice") in ("yes", "wait", "no"):
                    self.apply(task, msg["choice"])
        return self.offer()


def run_text(j: Jarvis):
    print("Text mode. Type a message; an empty line quits.")
    j.say(greeting())

    def console():
        while True:
            try:
                line = input().strip()
            except EOFError:
                return  # no keyboard (e.g. started in the background): keep serving the website
            j.bus.inbox.put({"type": "say", "text": line} if line else {"type": "quit"})
            if not line:
                return

    threading.Thread(target=console, daemon=True).start()
    while j.handle_pending():
        time.sleep(0.2)


def run_voice(j: Jarvis):
    j.say(greeting())
    while True:
        j.bus.set_state("idle")
        print('\nSay "Hey Jarvis"...')
        woke = j.ears.wait_for_wake_word(on_chunk=lambda level, score: j.bus.level(level), interrupt=j.has_work)
        if woke == "wake":
            j.voice.beep_listening()
            if not j.conversation():
                return
            j.voice.beep_done()
        if not j.handle_pending():
            return


def run_mic_test(voice: Voice):
    """Live check of the microphone, wake word and speech-to-text, without the AI brain."""
    from ears import Ears

    print("Loading speech models...")
    ears = Ears(is_busy=voice.busy.is_set)
    print(f"Microphone: {ears.mic_name}")
    print(f"Room noise level: {ears.noise:.0f}. Your voice needs to go above {ears.speech_threshold:.0f}.")
    print("If the bar doesn't move when you talk, Windows is using a different microphone:")
    print("  Settings > System > Sound > Input, pick the right one.")
    print('\nSay "Hey Jarvis", then a sentence. Press Ctrl+C to stop.\n')

    peak = 0.0

    def meter(level: float, score: float):
        nonlocal peak
        peak = max(score, peak * 0.9)  # hold near-misses on screen for a moment
        bar = "#" * min(30, int(30 * level / 3000))
        heard = "talking" if level > ears.speech_threshold else "quiet  "
        print(
            f"\r  mic {bar:<30} {level:5.0f} {heard} | wake word {peak:.2f} (needs {config.WAKE_THRESHOLD:.2f})",
            end="", flush=True,
        )

    while True:
        ears.wait_for_wake_word(on_chunk=meter)
        peak = 0.0
        print('\n\n  Heard "Hey Jarvis"! Now say a sentence...')
        voice.beep_listening()
        ears.flush()
        audio = ears.record()
        if audio is None:
            print("  No speech heard after the wake word. Try speaking louder or closer to the mic.\n")
        else:
            print(f'  You said: "{ears.transcribe(audio)}"\n')
        voice.beep_done()


def main():
    parser = argparse.ArgumentParser(description="Jarvis voice assistant")
    parser.add_argument("--text", action="store_true", help="type instead of talking")
    parser.add_argument("--mute", action="store_true", help="print replies instead of speaking")
    parser.add_argument("--mic-test", action="store_true", help="check that Jarvis can hear you")
    parser.add_argument("--no-browser", action="store_true", help="don't open the website at start")
    args = parser.parse_args()

    if args.mic_test:
        try:
            run_mic_test(Voice(config.VOICE, muted=args.mute))
        except KeyboardInterrupt:
            print("\nMic test finished.")
        return

    bus = Bus()
    memory = Memory(config.MEMORY_REPO, on_change=bus.set_memory)
    memory.load()
    print(f"Memory: {memory.status}")
    deep = DeepThinker(bus, memory)
    brain = Brain(deep=deep, memory=memory, on_tool=bus.action)
    # Right after logging in to Windows, Ollama may still be starting: give it up to a minute.
    for attempt in range(13):
        try:
            brain.setup()
            break
        except ConnectionError:
            if attempt == 0:
                print("Waiting for Ollama to start...")
            time.sleep(5)
    else:
        sys.exit(
            "Can't reach Ollama, which runs Jarvis's AI brain.\n"
            "Start the Ollama app from the Start menu (or install it from https://ollama.com), then try again."
        )

    voice = Voice(config.VOICE, muted=args.mute)
    bus.set_info(
        model=config.OLLAMA_MODEL, deep_model=config.DEEP_MODEL, memory=memory.status,
        mode="text" if args.text else "voice", call_me=config.CALL_ME,
    )
    if bus.start():
        site, local = bus.pair_urls()
        print(f"Website: {site}\n  (or on this PC only: {local})\n  Pairing code: {bus.token}")
        if config.OPEN_WEBSITE and not args.no_browser:
            webbrowser.open(site)
    else:
        print(f"(Website link unavailable: port {config.PORT} is busy. Is Jarvis already running?)")

    ears = None
    if not args.text:
        from ears import Ears  # slow import, only needed in voice mode

        print("Loading speech models (the first run downloads about 150 MB)...")
        ears = Ears(is_busy=voice.busy.is_set)

    j = Jarvis(voice, bus, brain, deep, ears)
    pc_tools.announce = j.say
    try:
        run_text(j) if args.text else run_voice(j)
    except KeyboardInterrupt:
        pass
    print("\nJarvis offline.")


if __name__ == "__main__":
    main()
