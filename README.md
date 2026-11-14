# 美丽 (MEILI)

> *美丽 (Meili) means "beautiful".*

---

<img width="865" height="427" alt="image" src="https://github.com/user-attachments/assets/4387c585-8eef-4c79-b0fd-69679bf4efb2" />

**A desktop overlay for reading, translating, and studying Chinese.**

---

## What is Meili?

Meili is a desktop application for Chinese text recognition, translation, and pronunciation support. It uses a transparent overlay to display recognized Chinese text alongside pinyin, vocabulary definitions, and English translations.

Meili can recognize subtitles from video playback, extract text from selected screen regions, and process text displayed in other desktop applications. It also includes audio recognition and text-to-speech functionality.

Processing runs locally on your machine.

## Features

### Live subtitle recognition

Meili can monitor a selected window and recognize subtitles within a user-defined screen region. Recognized text is displayed in the overlay with pinyin, vocabulary breakdowns, and translations.

Live mode also uses audio recognition to help identify spoken dialogue and correct subtitle recognition. Clicking the overlay background toggles playback of the selected media.

### Chinese text breakdown

Each recognized line includes the original Chinese characters, pinyin with tone marks, individual word meanings, and an English translation. This provides both a translation of the complete sentence and information about its vocabulary.

### Screen text recognition

Meili can recognize and translate Chinese text from other applications through screen selection or capture. Select a region of text to process it directly, or press **Ctrl+Alt+S** to capture the screen and extract any Chinese text it contains.

### Text-to-speech

Meili can read recognized Chinese text and English translations aloud, providing audio alongside the displayed text.

### Browser extension

An optional browser extension allows you to select Chinese text on webpages and view its translation directly within the page.

## Getting started

### Requirements

Meili requires Linux (tested on Wayland) and Python 3.12 or later. Node.js is only needed to build the optional browser extension. Chinese and English OCR language data are included in the repository. The extension requires a Chromium-based browser.

### Installation and execution

```bash
# Install system dependencies (Arch Linux)
./scripts/install_dependencies.sh

# Install Python dependencies
make install-pip

# Build the browser extension (optional)
make build-extension

# Create your local configuration
cp config/example_config.yaml config/config.yaml

# Run Meili
make run
```

To install the browser extension, navigate to `chrome://extensions`, enable Developer Mode, select **Load unpacked**, and choose `src/extension/dist`.

Meili uses default settings on first launch. Additional options, including language preferences, models, and GPU utilization, can be configured in `config/config.yaml`.

## Contributing

Contributions are welcome. Issues and pull requests can be submitted through the repository. See `AGENTS.md` for development notes.
