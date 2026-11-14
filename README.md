# 美丽 (MEILI)

> *美丽 (Meili) means "beautiful".*

---

<img width="865" height="427" alt="image" src="https://github.com/user-attachments/assets/4387c585-8eef-4c79-b0fd-69679bf4efb2" />


**A companion overlay for studying Chinese while you watch, listen, and browse.**

---

## What is Meili?

Meili is a lightweight, transparent overlay that helps you follow Chinese in real time. Whether you’re watching a show, listening to dialogue, or reading on a webpage, Meili puts the characters, pinyin, word meanings, and an English translation right on your screen — so you can keep up without breaking your flow.

Everything runs on your own machine.

## What you can do

### Follow along with shows and videos
Turn on **Live** mode, pick the window you’re watching, and drag a box over the subtitles. Meili reads the subtitles as they appear and translates them instantly, while also listening to the audio to catch and correct what’s being said. Click anywhere on the overlay background to play/pause your media.

### See more than just a translation
For each line, Meili shows the Chinese text, pinyin, a breakdown of word meanings, and a translation — giving you the context to actually learn, not just read along.

### Translate anything on your desktop
- **Select text** anywhere on your screen to translate it on the spot.
- Press **Ctrl+Alt+S** to capture what’s on screen and translate any Chinese it finds.

### Hear it out loud
Have Meili read the Chinese or the translation aloud to help with listening and pronunciation.

### Translate in your browser
With the included browser extension, select Chinese text on any page to see an in-page translation.

## Getting started

### Requirements
- Linux (tested on Wayland), Python 3.12+, and Node.js (for the browser extension)
- OCR language data for Chinese/English (included in this repo)
- A Chromium-based browser for the optional extension

### Install and run

```bash
# Install system dependencies (Arch Linux)
./scripts/install_dependencies.sh

# Install Python dependencies
make install-pip

# Build the browser extension (optional)
make build-extension

# Create your local config
cp config/example_config.yaml config/config.yaml

# Run Meili
make run
```

To use the browser extension, open `chrome://extensions`, enable Developer Mode, choose **Load unpacked**, and select `src/extension/dist`.

> Meili works out of the box with the default settings. You can tweak behavior (like language, models, or GPU use) in `config/config.yaml` if you’d like.

## Contributing

Contributions are welcome — feel free to open an issue or pull request. See `AGENTS.md` for development notes.
