"""
Application entry point: hotkeys, capture, OCR, translation, TTS, server.
"""

import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .config import ConfigTemplate, SystemSpecs
from .ocr import OcrService
from .translation import TranslationService
from .tts import SpeechSynthesizer
from .server.server import Server
from .utils import Logger, HotkeyManager
from .capture import ScreenCapture
from .window.hud import HUDWindow


class HotkeySignals(QObject):
    """Qt signals for thread-safe hotkey handling."""
    screenshot_requested = pyqtSignal()


class MeslyApp:
    def __init__(self):
        print("Initializing Mesly...")
        self.config = ConfigTemplate.get_config()

        # Detect system specs for feature gating (e.g. NeuTTS)
        self.specs = SystemSpecs()
        Logger.info(f"System specs: {self.specs.get_specs_summary()}")

        # Setup hotkeys and screen capture
        self.hotkey_manager = HotkeyManager()
        self.screen_capture = ScreenCapture()

        # Signal handler for thread-safe screenshot
        self.signals = HotkeySignals()
        self.signals.screenshot_requested.connect(self._capture_screenshot)

        self._register_hotkeys()

        app = QApplication(sys.argv)
        app.setApplicationName("Mesly")
        app.setStyle("Fusion")

        # Ctrl+C / SIGTERM should quit the app gracefully. The default Python
        # SIGINT handler can never run while Qt's C++ event loop owns the
        # thread, so an unhandled KeyboardInterrupt stays pending and fires
        # at interpreter shutdown (ugly traceback, abort exit code).
        signal.signal(signal.SIGINT, self._handle_quit_signal)
        signal.signal(signal.SIGTERM, self._handle_quit_signal)

        # Yield to Python periodically so the signal handlers get a chance
        # to actually run while the Qt event loop is active.
        self._signal_timer = QTimer()
        self._signal_timer.timeout.connect(lambda: None)
        self._signal_timer.start(200)

        # Local services: OCR, translation (MarianMT zh->en) and speech (NeuTTS/gTTS)
        self.ocr_service = OcrService(self.config)
        self.translation_service = TranslationService(
            model_name=self.config.translation.model, config=self.config)
        self.speech = SpeechSynthesizer(self.config, specs=self.specs)

        self.window = HUDWindow(self.translation_service, self.speech, self.ocr_service)
        self.window.show()

        # Start hotkey listeners
        self.hotkey_manager.start()
        Logger.info("Hotkey listener started - Ctrl+Alt+S to screenshot")

        self.server = Server(
            host="127.0.0.1",
            port=8263,
            translation_service=self.translation_service,
            config=self.config
        )
        self.server.start()
        Logger.info("FastAPI server started on http://127.0.0.1:8263")

        # Cleanup on exit
        app.aboutToQuit.connect(self._cleanup)

        sys.exit(app.exec())

    def _handle_quit_signal(self, signum, frame):
        """Quit the Qt event loop so cleanup runs and the app exits cleanly."""
        Logger.info(f"Signal {signum} received, shutting down...")
        QApplication.quit()

    def _cleanup(self):
        """Cleanup resources before application exit."""
        Logger.info("Cleaning up resources...")

        if self.window:
            self.window.shutdown()

        if self.hotkey_manager:
            self.hotkey_manager.stop()
            Logger.info("Hotkey manager stopped")

        if self.translation_service:
            self.translation_service.close()

        if self.speech:
            self.speech.close()

        Logger.info("Cleanup complete")
        # Hard exit: native inference threads (whisper/ctranslate2)
        # cannot be interrupted, and a polite exit can hang on them
        os._exit(0)

    def _register_hotkeys(self):
        """Register Ctrl+Alt+S for screenshot."""
        self.hotkey_manager.register(
            '<ctrl>+<alt>+s',
            self._on_screenshot_hotkey
        )
        Logger.info("Registered hotkey: Ctrl+Alt+S (Screenshot)")

    def _on_screenshot_hotkey(self):
        """Handle screenshot hotkey press (runs in hotkey thread)."""
        Logger.info("Screenshot hotkey pressed (Ctrl+Alt+S)")
        # Emit signal to capture screenshot in main thread
        self.signals.screenshot_requested.emit()

    def _capture_screenshot(self):
        """Capture screenshot (runs in main thread)."""
        screenshot_path = Path(__file__).resolve().parent.parent.parent / "data" / "screenshots"
        screenshot_path.mkdir(parents=True, exist_ok=True)

        for item in screenshot_path.iterdir():
            if item.is_file():
                item.unlink()

        # Minimize window to avoid capturing it
        was_minimized = self.window.isMinimized()
        if not was_minimized:
            self.window.showMinimized()

        # Small delay to let window minimize and X11 to settle
        QTimer.singleShot(100, self._do_capture)

    def _do_capture(self):
        """Actually perform the capture after delay."""
        # Generate filepath with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"data/screenshots/screenshot_{timestamp}.png"

        # Create directory if needed
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # Capture and save
        success = self.screen_capture.capture_and_save(filepath)

        # Restore window
        self.window.showNormal()

        if not success:
            Logger.error("Failed to capture screenshot")
            self.window.lbl_status.setText("Failed to capture screenshot")
            return

        Logger.info(f"Screenshot saved: {filepath}")

        # Perform OCR on the screenshot
        try:
            Logger.info("Performing OCR on screenshot...")
            with Image.open(filepath) as img:
                ocr_text = self.ocr_service.image_to_text(img)

            if ocr_text:
                Logger.info(f"OCR extracted {len(ocr_text)} characters")
                # Re-open for display (the previous handle is closed)
                with Image.open(filepath) as preview_img:
                    self.window.show_ocr_text(ocr_text, image=preview_img)
            else:
                Logger.warning("No text found in screenshot")
                self.window.lbl_status.setText("No text detected in screenshot")
                # Still show what was captured
                with Image.open(filepath) as preview_img:
                    self.window._set_preview(preview_img)
        except Exception as e:
            Logger.error(f"OCR failed: {e}")
            self.window.lbl_status.setText(f"OCR error: {e}")
