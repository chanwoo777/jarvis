"""Speaking: turns Jarvis's replies into audio, plus the little beeps."""

import asyncio
import io
import re
import threading

import edge_tts
import numpy as np
import sounddevice as sd
import soundfile as sf

BEEP_RATE = 44100


def _tone(freq: float, ms: int, volume: float = 0.2) -> np.ndarray:
    t = np.linspace(0, ms / 1000, int(BEEP_RATE * ms / 1000), endpoint=False)
    fade = np.minimum(1, np.minimum(t, t[::-1]) * 200)  # 5 ms fade in/out, no clicks
    return (volume * np.sin(2 * np.pi * freq * t) * fade).astype(np.float32)


def clean_for_speech(text: str) -> str:
    """Remove markdown symbols that would be read out loud."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"[*_#`>|]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]", "", text)  # emoji
    return re.sub(r"\s+", " ", text).strip()


class Voice:
    def __init__(self, voice_name: str, muted: bool = False):
        self.voice_name = voice_name
        self.muted = muted
        self.busy = threading.Event()  # set while audio is playing
        self._lock = threading.Lock()  # one sound at a time (timers speak from other threads)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        async def fetch() -> bytes:
            audio = bytearray()
            async for chunk in edge_tts.Communicate(text, self.voice_name).stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
            return bytes(audio)

        mp3 = asyncio.run(fetch())
        data, rate = sf.read(io.BytesIO(mp3), dtype="float32")
        return data, rate

    def _play(self, data: np.ndarray, rate: int):
        with self._lock:
            self.busy.set()
            try:
                sd.play(data, rate)
                sd.wait()
            finally:
                self.busy.clear()

    def say(self, text: str):
        text = clean_for_speech(text)
        if not text or self.muted:
            return
        try:
            self._play(*self.synthesize(text))
        except Exception as e:
            # No internet for the neural voice: fall back to the built-in Windows voice.
            print(f"(online voice failed: {e}; using offline voice)")
            self._say_offline(text)

    def _say_offline(self, text: str):
        import pyttsx3

        with self._lock:
            self.busy.set()
            try:
                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()
            finally:
                self.busy.clear()

    def beep_listening(self):
        if not self.muted:
            self._play(np.concatenate([_tone(660, 70), _tone(990, 90)]), BEEP_RATE)

    def beep_follow_up(self):
        if not self.muted:
            self._play(_tone(990, 60, volume=0.1), BEEP_RATE)

    def beep_done(self):
        if not self.muted:
            self._play(np.concatenate([_tone(880, 70), _tone(587, 90)]), BEEP_RATE)
