# DANNAZIONE DI PROVVIDENZA

A local-first language learning tool: OCR anything on your screen, translate it with a local model, and hear it spoken aloud. Built for learning languages while gaming or reading.

## Features

### OCR + Translate (the core)
* **Hotkey:** `Ctrl+Alt+S` captures your screen, extracts text with OCR (Tesseract), and translates it.
* **Paste mode:** paste characters straight into the app and hit Translate.
* **Live capture:** optional 5-second fullscreen capture with automatic OCR + translation while you play or read.
* **Engine:** local **Helsinki-NLP (MarianMT)** — multi-language to English. No cloud API, no API keys, no per-request costs.

### Browser Extension (Chromium)
* Select text on any page and get an in-page translation tooltip.
* The extension talks to the local backend on `127.0.0.1:8263`.
* Page context (last few pages) is kept **in memory only** — nothing is written to disk.

### Text-to-Speech
* **NeuTTS** (local neural TTS, optional — enabled in config).
* **gTTS** fallback (free Google TTS endpoint).
* Speak either the captured text or its translation, useful for pronunciation.

## What it does NOT do (by design)

* No LLM calls — there is no agent, no chat, no cloud AI.
* No browsing history stored — no database of pages you visit.
* No telemetry; your reading habits never leave your machine.

## Installation

### Prerequisites
* Python 3.12+
* Node.js (latest LTS)
* Tesseract OCR with language packs (e.g. `tesseract-ocr-chi-sim` for Mandarin)
* Chromium-based browser (for the extension)

### Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/Dannazione-di-Provvidenza.git
cd Dannazione-di-Provvidenza

# System dependencies (Arch Linux)
./scripts/install_deps.sh

# Python dependencies
make install-pip

# Vendor dependencies (optional, NeuTTS only)
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
  neutts_enabled: false
```

### Run

```bash
python main.py
```

### Load Extension

1. Build it: `make build-extension`
2. Open `chrome://extensions`, enable Developer Mode
3. "Load unpacked" and select the extension build output (`src/extension/dist`)

## Hotkeys

| Combination | Function |
|-------------|----------|
| `Ctrl+Alt+S` | Screenshot + OCR + translate |

## Project Structure

```
Dannazione-di-Provvidenza/
├── src/
│   ├── mesly/              # Python application
│   │   ├── capture/         # Screen capture (hotkey + live stream)
│   │   ├── config/         # Settings and system specs
│   │   ├── server/         # FastAPI backend (translation, page context)
│   │   ├── translation/    # Local MarianMT translation service
│   │   ├── tts/            # NeuTTS / gTTS speech synthesis
│   │   └── window/         # PyQt5 GUI
│   └── extension/          # Chromium extension (select-to-translate)
├── config/                 # Runtime config
├── vendor/                 # NeuTTS (optional)
├── scripts/                # Install scripts
└── main.py                 # Entry point
```

## Contributing

Contributions welcome. See `AGENTS.md` for development guidelines:
- Import at top level
- Separate modules into folders
- Use classes in extensions

## License

MIT — do whatever you want.
