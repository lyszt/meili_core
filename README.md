# DANNAZIONE DI PROVVIDENZA

> *"Damnation of Providence / Damn Providence"* — For when divine foresight becomes an instrument of control, and some may not like it.

---

<img width="736" height="414" alt="image" src="https://github.com/user-attachments/assets/9600986f-47b9-41f8-979f-557508b6ede3" />

**LANGUAGE LEARNING • LOCAL TRANSLATION • TEXT-TO-SPEECH**

*A local-first language study tool*

---

## What is this?

**Dannazione di Provvidenza** is a language study tool: capture text from your screen, get a translation from a local model, and hear it spoken. Made for studying a language while gaming or reading without tabbing out to a translator. Ships with a Chromium extension for select-to-translate on any page.

## Features

### 1. OCR + Translate
* **Hotkey:** `Ctrl+Alt+S` captures the screen, extracts text with OCR (Tesseract), translates it, and shows it in the app window.
* **Paste mode:** paste characters straight into the app and hit Translate.
* **Engine:** local **Helsinki-NLP (MarianMT)** — no API keys, no cloud calls.
* **Privacy:** fully offline capable. Your reading habits never leave your machine.

### 2. Live window share
* OBS-style source picker: choose an open window, the entire screen, or use the system picker dialog.
* On Wayland (and anywhere the desktop portal is available), "Pick window/screen" opens the native portal dialog and streams real frames over PipeWire — same mechanism OBS uses.
* Live preview; the capture follows the window when it moves or resizes; auto OCR + translate on an interval (or on demand), shown right in the live window.
* Requires PyGObject + GStreamer + the PipeWire GStreamer plugin for the portal path; `wmctrl`/`xdotool` for the X11 window list.

### 3. Text-to-Speech
* **NeuTTS** (local neural TTS, optional — enabled in config).
* **gTTS** fallback.
* Speak either the captured text or its translation, useful for pronunciation.

### 4. Browser Extension (Chromium)* Select text on any page and get an in-page translation tooltip.
* Talks to the local backend on `127.0.0.1:8263`.
* Page context is kept **in memory only** — nothing is written to disk.

## Installation

### Prerequisites
* Python 3.12+
* Node.js (latest LTS)
* Tesseract OCR with the language packs you want (e.g. `chi_sim` for Mandarin)
* `wmctrl` and `xdotool` for the live window share's window picker (X11)
* Chromium-based browser (for the extension)

### Setup

```bash
# System dependencies (Arch Linux)
./scripts/install_dependencies.sh

# Python dependencies
make install-pip

# Optional: NeuTTS
make vendor

# Browser extension
make build-extension

# Configuration
cp config/example_config.yaml config/config.yaml
```

### Configuration

Edit `config/config.yaml`:

```yaml
ocr:
  engine: "pytesseract"
  languages: ["en", "zh"]

translation:
  service: "helsinki-nlp"
  target_language: "en"

performance:
  use_gpu: false
  neutts_enabled: false   # needs vendor/neutts and src/assets/voice_ref.wav
```

### Run

```bash
make run
```

### Load Extension

1. Build it: `make build-extension`
2. Open `chrome://extensions`, enable Developer Mode
3. "Load unpacked" and select the extension build output (`src/extension/dist`)

---

## Hotkeys

| Combination | Function |
|-------------|----------|
| `Ctrl+Alt+S` | Screenshot + OCR + translate |

---

## Project Structure

```
Dannazione-di-Provvidenza/
├── src/
│   ├── mesly/              # Python application
│   │   ├── capture/         # Screen capture (hotkey, live stream, window share)
│   │   ├── config/          # Settings and system specs
│   │   ├── server/          # FastAPI backend (translation, page context)
│   │   ├── translation/     # Local MarianMT translation service
│   │   ├── tts/             # NeuTTS / gTTS speech synthesis
│   │   └── window/          # PyQt5 GUI (main + live share)
│   └── extension/           # Chromium extension (select-to-translate)
├── config/                  # Runtime config
├── vendor/                  # NeuTTS (optional)
├── scripts/                 # Install scripts
└── main.py                  # Entry point
```

---

## Contributing

Contributions welcome. See `AGENTS.md` for development guidelines:
- Import at top level
- Separate modules into folders
- Use classes in extensions
