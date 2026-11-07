"""
Application entry point: hotkeys, capture, OCR, translation, TTS, server.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytesseract
from PIL import Image
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from .config import ConfigTemplate, SystemSpecs
from .translation import TranslationService
from .tts import SpeechSynthesizer
from .server.server import Server
from .utils import Logger, HotkeyManager
from .capture import ScreenCapture
from .window.main_window import MainWindow


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

        # Local services: translation (MarianMT) and speech (NeuTTS/gTTS)
        self.translation_service = TranslationService()
        self.speech = SpeechSynthesizer(self.config, specs=self.specs)

        self.window = MainWindow(self.translation_service, self.speech)
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

    def _cleanup(self):
        """Cleanup resources before application exit."""
        Logger.info("Cleaning up resources...")

        if self.hotkey_manager:
            self.hotkey_manager.stop()
            Logger.info("Hotkey manager stopped")

        if self.translation_service:
            self.translation_service.close()

        if self.speech:
            self.speech.close()

        Logger.info("Cleanup complete")

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
                ocr_text = pytesseract.image_to_string(img).strip()

            if ocr_text:
                Logger.info(f"OCR extracted {len(ocr_text)} characters")
                self.window.show_ocr_text(ocr_text)
            else:
                Logger.warning("No text found in screenshot")
                self.window.lbl_status.setText("No text detected in screenshot")
        except Exception as e:
            Logger.error(f"OCR failed: {e}")
            self.window.lbl_status.setText(f"OCR error: {e}")
