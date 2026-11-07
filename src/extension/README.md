# Dannazione - Browser Extension

Chromium (Manifest V3) extension for select-to-translate, built with Lit. Talks to the local Python backend started by the main application.

## Features

- **Select-to-translate** - select text on any page and get an in-page translation tooltip
- **Popup** - translate your current selection, pick source/target language, toggle the overlay
- **Local backend** - all translations go to the MarianMT server on `127.0.0.1:8263` (started by `make run` in the repo root)

## Build

From the repo root:

```bash
make build-extension
```

Or directly:

```bash
cd src/extension
npm install
npm run build
```

## Load in Chromium

1. Build the extension (see above)
2. Open `chrome://extensions` and enable Developer Mode
3. "Load unpacked" and select `src/extension/dist`

## Project Structure

```
src/extension/src/
├── background/     # Service worker: message routing, page context push, translation calls
├── content/        # Content script: selection listener + translation overlay
├── popup/          # Popup UI (Lit component)
├── config/         # Backend base URL
├── dannazione/     # API client for the local backend
└── styles/         # Shared styles
```

## Configuration

The backend base URL is set in `src/config/index.js` (default `http://127.0.0.1:8263`). The backend must be running (`make run` in the repo root).
