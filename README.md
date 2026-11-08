# 美丽 (MEILI)

> *美丽 (Meili) means "beautiful".*

---

<img width="865" height="427" alt="image" src="https://github.com/user-attachments/assets/4387c585-8eef-4c79-b0fd-69679bf4efb2" />


**MANDARIN STUDY HUD • LOCAL TRANSLATION • TEXT-TO-SPEECH**

---

## What is this?


Meili (美丽) is a software that allows you to translate Chinese live, with a transparent overlay with pinyin and meaning.

## Features

### 1. Watch region
* On startup, you pick the window to share in the system dialog.
* Click the overlay to open a frozen frame of the stream, then draw a box over it to set the watched region (right-click or Esc cancels).
* The app keeps watching that area of the shared window: every 3 seconds it reads the Chinese there and translates it only when a new line appears.
* Right-click the overlay to clear the region.

### 2. Study card
* Each result shows hanzi, pinyin (`pypinyin`), a word breakdown from **CC-CEDICT**, and the translation (local MarianMT, `Helsinki-NLP/opus-mt-zh-en`).
* The card sits horizontally centered at the bottom of the overlay. The app draws the text with an outline so it stays readable over video.

### 3. Selection translate
* Select Chinese text anywhere on the desktop and the app runs it through the same pipeline: CJK filter → card → translation.

### 4. Hotkey
* Press `Ctrl+Alt+S` to capture the screen. The app OCRs it and translates any Chinese found.

### 5. Text-to-Speech
* **NeuTTS** (local neural TTS, optional, enabled in config).
* **gTTS** fallback.
* The app speaks the hanzi or the translation, in Chinese or English accordingly.

### 6. Browser Extension (Chromium)
* Select Chinese text on a page and the extension shows an in-page translation tooltip.
* The extension talks to the local backend on `127.0.0.1:8263`.
* The extension keeps page context **in memory only**. It writes nothing to disk.

## Installation

### Prerequisites
* Python 3.12+
* Node.js (latest LTS, for the browser extension)
* Tesseract OCR with `chi_sim` and `eng` traineddata (vendored in `data/tessdata/`)
* PyGObject + GStreamer + the PipeWire GStreamer plugin (for the portal share on Wayland)
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
  languages: ["en", "zh"]     # chi_sim does the hanzi work

translation:
  service: "helsinki-nlp"
  model: "Helsinki-NLP/opus-mt-zh-en"   # Chinese -> English
  target_language: "en"

performance:
  use_gpu: false
  neutts_enabled: false   # needs vendor/neutts and src/assets/voice_ref.wav
```

`use_gpu: false` runs the translation model on the CPU.

### Run

```bash
make run
```

### Load Extension

1. Build it: `make build-extension`
2. Open `chrome://extensions`, enable Developer Mode
3. "Load unpacked" and select the extension build output (`src/extension/dist`)

---

## Project Structure

```
Meili/
├── src/
│   ├── mesly/              # Python application
│   │   ├── capture/        # Portal/PipeWire window streaming, screen capture
│   │   ├── config/         # Settings and system specs
│   │   ├── dictionary/     # CC-CEDICT lookup, pinyin, segmentation
│   │   ├── ocr/            # Tesseract OCR + CJK-only filtering
│   │   ├── server/         # FastAPI backend (extension endpoint)
│   │   ├── translation/    # Local MarianMT (opus-mt-zh-en) service
│   │   ├── tts/            # NeuTTS / gTTS speech synthesis
│   │   ├── utils/          # Logging, hotkeys
│   │   └── window/         # PyQt5 HUD overlay
│   └── extension/           # Chromium extension (select-to-translate)
├── data/                    # Vendored tessdata + CC-CEDICT
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
