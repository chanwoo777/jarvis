"""Settings, read from the .env file next to this script."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

CALL_ME = os.getenv("JARVIS_CALL_ME", "").strip()
VOICE = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en")
WAKE_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:2b")
DEEP_MODEL = os.getenv("DEEP_MODEL", "qwen3.5:4b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Long-term memory lives in this private GitHub repo (owner/name). Blank = remember only until Jarvis closes.
MEMORY_REPO = os.getenv("JARVIS_MEMORY_REPO", "").strip()

# The website that shows Jarvis, and whether to open it when Jarvis starts.
WEBSITE_URL = os.getenv("JARVIS_WEBSITE", "https://chanwoo777.github.io/jarvis/").strip()
OPEN_WEBSITE = os.getenv("JARVIS_OPEN_WEBSITE", "yes").strip().lower() in ("yes", "true", "1")
PORT = int(os.getenv("JARVIS_PORT", "8765"))
_site = urlparse(WEBSITE_URL)
WEBSITE_ORIGIN = f"{_site.scheme}://{_site.netloc}"

SAMPLE_RATE = 16000
# openWakeWord expects 80 ms chunks of 16 kHz audio.
CHUNK = 1280
