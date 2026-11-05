# Jarvis

A voice assistant for a Windows PC, inspired by the one in the Iron Man films. Say **"Hey Jarvis"**,
ask something, and it answers out loud, while a live website shows Jarvis thinking and acting.
**Free, with no API keys:** the AI runs on your own PC.

- **Quick answers** from a small, fast AI model for chat and commands.
- **Deep thinking** for detailed questions. A bigger model works on them in the background while
  you keep talking. When the answer is ready, Jarvis asks *"Shall I tell you now?"*:
  - **yes:** it tells you
  - **wait:** it holds the answer and offers it again a few minutes later
  - **no:** it stays quiet, but the answer is kept in memory (ask for it any time)
- **Long-term memory** in a private GitHub repo, not on your PC's disk.
- **Live website** at https://chanwoo777.github.io/jarvis/ showing the animated orb, the
  conversation, live thinking, actions on your PC, answers waiting for you, and memories.

## How it works

```
Laptop:  mic → "Hey Jarvis" → speech-to-text → quick brain (qwen3.5:2b) + PC tools → voice
                                                     │
                                                     └→ deep brain (qwen3.5:4b, in the background)
              │ private link on this PC only (pairing code)          │ memories
              ▼                                                      ▼
Browser: chanwoo777.github.io/jarvis (Jarvis's face)    private GitHub repo: jarvis-memory
```

The website is only a "face": GitHub Pages hosts plain web pages, so all the thinking and PC
control happen in the Jarvis program on your laptop. The page connects to it on your own computer
(127.0.0.1, port 8765). Other websites can't connect: Jarvis only accepts its own site, and only
with the pairing code it makes fresh at every start.

| File | Job |
|---|---|
| `main.py` | Ties it together: wake word, conversation, "Shall I tell you now?", website commands |
| `ears.py` | Microphone, wake word, turning speech into text |
| `brain.py` | Quick brain: answers, uses tools, hands detailed questions to deep thinking |
| `deep.py` | Deep thinking in the background, and the yes/wait/no answers |
| `memory.py` | Long-term memory in the private GitHub repo |
| `bus.py` | The live link to the website (and serves it locally at http://localhost:8765) |
| `pc_tools.py` | What Jarvis can do: web search, weather, apps, music, volume, timers... |
| `voice.py` | Turns text into speech, plays the beeps |
| `launcher.py` | Runs from login; starts Jarvis when the website asks |
| `docs/` | The website (published by GitHub Pages) |
| `config.py` | Reads your settings from `.env` |

## Setup

Already done on this PC:
- **Ollama** (runs the AI models) is installed and starts with Windows, with **qwen3.5:2b** (quick)
  and **qwen3.5:4b** (deep) downloaded.
- The **GitHub CLI** is signed in, which Jarvis uses to reach its memory repo.
- The Python packages are installed in `.venv`.

Optional: open `.env` in Notepad and set `JARVIS_CALL_ME=` to what Jarvis should call you.

On a new PC: install Ollama (https://ollama.com) and the GitHub CLI (`gh auth login`), then run
`.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## Run it

Make sure Ollama is running (llama icon in the system tray). Then double-click `run_jarvis.bat`.
Jarvis starts and opens the website with the pairing code filled in.
The first time, Chrome may ask to let the site reach apps on this device: choose **Allow**.

- Say **"Hey Jarvis"**, wait for the beep, and talk. Or click the mic button on the website, or type there.
- Keep talking without "Hey Jarvis" until you go quiet.
- For detailed questions, say things like **"Think about how I should plan my trip"**. Jarvis
  works on it in the background; watch the *Deep thinking* panel. Answer *"Shall I tell you now?"*
  by voice ("yes", "wait", "no") or with the buttons.
- **"Remember that my exam is on Friday"** saves a memory. **"What do you remember about my exam?"** recalls it.
- Say **"Goodbye"**, or press Ctrl+C in the Jarvis window, to quit.

**Starts with Windows, and from the website:** a shortcut in your Startup folder runs
`launcher.py` at login. It starts Jarvis (minimized) and opens the website, then keeps waiting
quietly (it uses almost no memory). Whenever you open https://chanwoo777.github.io/jarvis/ and
Jarvis isn't running, the page asks the launcher, which starts Jarvis and hands the page its
pairing code. No second tab, nothing to type. The launcher only accepts Jarvis's own website and
can only start Jarvis. The page starts Jarvis automatically once per visit, never after you closed
Jarvis yourself; the **Start Jarvis** button is there for that.

To stop all of this, press Win+R, type `shell:startup`, delete `Jarvis.lnk`, and restart the PC
(or end `pythonw.exe` in Task Manager).

Type instead of talking: `.venv\Scripts\python.exe main.py --text`.
If GitHub Pages is unavailable, the same site works at http://localhost:8765 while Jarvis runs.

## Fixing problems

**Start with the mic test** if Jarvis doesn't hear you: double-click `mic_test.bat`. It shows how
loud the mic hears you and how sure it is you said "Hey Jarvis" (it must reach 0.50).

| Problem | Fix |
|---|---|
| Website says "Jarvis is offline" | Start Jarvis on your laptop. The site only works while Jarvis runs |
| Website says "Pairing code expired" | Jarvis was restarted. Use the tab it just opened, or type the code from the Jarvis window |
| Website can't connect at all | Allow "access other apps on this device" in Chrome (padlock icon > Site settings), or use http://localhost:8765 |
| "Can't reach Ollama" | Open "Ollama" from the Start menu, wait a few seconds, try again |
| Everything slows down during deep thinking | Both AI models are in memory (about 6 GB). Close Chrome tabs and other big apps. The deep model unloads 3 minutes after it finishes |
| Answers are too simple | Set `OLLAMA_MODEL=qwen3.5:4b` in `.env` (smarter, slower) |
| Jarvis doesn't react to "Hey Jarvis" | Run the mic test; lower `WAKE_THRESHOLD` in `.env` to `0.3` |
| It mishears words | Set `WHISPER_MODEL=small.en` (slower but more accurate) |
| Memory says "session only" or "offline" | Check `gh auth status`, and that `JARVIS_MEMORY_REPO` in `.env` names your private repo |

## Privacy

- The wake word, speech recognition and both AI models run on your PC.
- Memories are stored in your **private** GitHub repo `jarvis-memory`, which only you can see.
  View, edit or delete them on github.com. Nothing is written to your PC's disk.
- This code repo is **public** (free GitHub Pages needs that) and holds no memories or personal data.
- Over the internet go: web searches (DuckDuckGo), weather (Open-Meteo), Jarvis's reply text to
  Microsoft's speech service for the voice, and memories to GitHub.
