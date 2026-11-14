# 美丽 (MEILI)

> *美丽 (Meili) means "beautiful".*

---

<img width="865" height="427" alt="image" src="https://github.com/user-attachments/assets/4387c585-8eef-4c79-b0fd-69679bf4efb2" />


**MANDARIN STUDY HUD • LOCAL TRANSLATION • TEXT-TO-SPEECH**

---

## What is this?

**Meili** is a transparent always-on-top overlay for studying Chinese. It can transcribe and translate spoken Chinese from desktop audio, and can also read on-screen subtitles from a shared window. Everything runs locally.

## Features

### 1. Live mode (visual + audio, off by default)
* Click **Live** to start the combined mode: it listens to desktop audio and watches on-screen subtitles.
* Pick a window in the system portal dialog (PipeWire, like OBS), then drag a box on the overlay over the subtitles to mark the watched region.
* When a new subtitle appears, the app reads and translates it immediately from the image; recognized speech retrofixes/corrects the matching subtitle when possible. Unrelated audio won’t replace the current visual subtitle.
* Right-click the overlay to clear the region; toggle **Live** off to stop.
* The **Trans** button toggles translation on/off (default on).

### 2. Study card
* Each result shows hanzi, pinyin (`pypinyin`), a word breakdown from **CC-CEDICT**, and, when translation is on, the translation (local seq2seq model, default `facebook/nllb-200-distilled-600M`, configurable).
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
  service: "nllb"
  model: "facebook/nllb-200-distilled-600M"   # Chinese -> English (better quality)
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
│   │   ├── translation/    # Local seq2seq translation service (NLLB/MarianMT)
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
