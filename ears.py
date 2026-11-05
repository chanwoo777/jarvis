"""Hearing: microphone input, "Hey Jarvis" wake word, and speech-to-text."""

import os
import queue
from collections import deque

# Quiet harmless Hugging Face download warnings (Windows symlinks, no login).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

import numpy as np
import openwakeword.utils
import sounddevice as sd
from faster_whisper import WhisperModel
from openwakeword.model import Model

import config

CHUNK_SECONDS = config.CHUNK / config.SAMPLE_RATE


def rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))


class Ears:
    def __init__(self, is_busy=lambda: False):
        # is_busy() is True while Jarvis is talking, so it doesn't hear itself.
        self.is_busy = is_busy
        self.chunks: queue.Queue[np.ndarray] = queue.Queue()

        openwakeword.utils.download_models(model_names=["hey_jarvis"])
        self.wake_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self.whisper = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")

        self.stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=config.CHUNK,
            callback=lambda data, frames, t, status: self.chunks.put(data[:, 0].copy()),
        )
        self.stream.start()
        self.noise = self._measure_noise()

    def _read(self) -> np.ndarray:
        return self.chunks.get(timeout=2)

    def _measure_noise(self, seconds: float = 1.0) -> float:
        levels = [rms(self._read()) for _ in range(int(seconds / CHUNK_SECONDS))]
        return max(float(np.median(levels)), 30.0)

    @property
    def mic_name(self) -> str:
        return sd.query_devices(self.stream.device)["name"]

    @property
    def speech_threshold(self) -> float:
        """How loud (RMS) audio must be to count as someone speaking."""
        return max(self.noise * 4, 300)

    def flush(self):
        """Throw away audio heard so far (e.g. Jarvis's own voice)."""
        while not self.chunks.empty():
            self.chunks.get_nowait()

    def wait_for_wake_word(self, on_chunk=None, interrupt=None) -> str:
        """Block until "Hey Jarvis" is heard (returns "wake"), or until interrupt() is true
        (returns "interrupted"; e.g. a message from the website). on_chunk(level, score), if
        given, is called for every 80 ms of audio (for live meters)."""
        self.flush()
        self.wake_model.reset()
        while True:
            chunk = self._read()
            if interrupt and interrupt():
                return "interrupted"
            if self.is_busy():
                continue
            level = rms(chunk)
            if level < self.noise * 2:
                # Slowly follow the room's background noise level.
                self.noise = 0.95 * self.noise + 0.05 * level
            score = max(self.wake_model.predict(chunk).values())
            if on_chunk:
                on_chunk(level, score)
            if score >= config.WAKE_THRESHOLD:
                self.wake_model.reset()
                return "wake"

    def record(self, max_wait: float = 6.0, max_length: float = 15.0, end_silence: float = 1.0,
               on_chunk=None, interrupt=None):
        """Record one spoken command. Returns float32 audio, or None if nobody spoke (or if
        interrupt() turned true before they started). on_chunk(level) gets every 80 ms of audio."""
        threshold = self.speech_threshold
        pre_roll: deque[np.ndarray] = deque(maxlen=4)
        frames: list[np.ndarray] = []
        waited = silent = 0.0

        while True:
            chunk = self._read()
            level = rms(chunk)
            if on_chunk:
                on_chunk(level)
            loud = level > threshold
            if not frames:
                if interrupt and interrupt():
                    return None
                pre_roll.append(chunk)
                if loud:
                    frames.extend(pre_roll)
                    continue
                waited += CHUNK_SECONDS
                if waited >= max_wait:
                    return None
                continue

            frames.append(chunk)
            silent = 0.0 if loud else silent + CHUNK_SECONDS
            if silent >= end_silence or len(frames) * CHUNK_SECONDS >= max_length:
                break

        return np.concatenate(frames).astype(np.float32) / 32768.0

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self.whisper.transcribe(
            audio,
            language=config.WHISPER_LANGUAGE,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()
