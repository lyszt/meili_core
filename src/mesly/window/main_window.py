"""
Main application window: fullscreen capture preview, OCR text, translation, TTS.
"""

import os
import tempfile
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
                             QPushButton, QLabel, QTextEdit, QCheckBox)
from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from ..capture.stream_thread import ScreenShareThread
from ..ocr import OcrService
from ..translation import TranslationService
from ..tts import SpeechSynthesizer
from ..utils import Logger
from .live_view import LiveViewWindow
from .shared import TranslationWorker, capped_window_size, pil2pixmap


class MainWindow(QMainWindow):
    # Emitted from non-GUI threads to play audio safely on the main thread
    play_audio_signal = pyqtSignal(str)

    def __init__(self, translation_service: TranslationService, speech: SpeechSynthesizer,
                 ocr_service: OcrService):
        super().__init__()
        self.play_audio_signal.connect(self._play_audio_file)

        self.setWindowTitle("Mesly - OCR Translate")
        width, height = capped_window_size(520, 800, 0.45, 0.75)
        self.resize(width, height)

        # Tools
        self.translation_service = translation_service
        self.speech = speech
        self.ocr_service = ocr_service
        self.stream_thread = None
        self.translation_worker = None
        self.live_view = None
        self.audio_player = QMediaPlayer()
        self.audio_player.error.connect(self._on_audio_error)

        # UI Setup
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Title
        title_label = QLabel("Mesly — OCR Language Tool")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title_label)

        # Start/Stop Capture Button
        self.btn_toggle_share = QPushButton("Start Fullscreen Capture")
        self.btn_toggle_share.setCheckable(True)
        self.btn_toggle_share.clicked.connect(self.toggle_sharing)
        self.btn_toggle_share.setStyleSheet("padding: 10px; font-size: 14px;")
        layout.addWidget(self.btn_toggle_share)

        # Live Window Share Button (OBS-style picker)
        self.btn_live_share = QPushButton("Open Live Window Share")
        self.btn_live_share.clicked.connect(self.open_live_view)
        self.btn_live_share.setStyleSheet("padding: 8px; font-size: 12px;")
        layout.addWidget(self.btn_live_share)

        # Preview Area
        self.lbl_preview = QLabel("Screen Preview")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setStyleSheet("border: 2px dashed #555; background: #222; color: #888;")
        self.lbl_preview.setMinimumSize(320, 180)
        layout.addWidget(self.lbl_preview, 2)
        self._last_preview_image = None

        # Status Label
        self.lbl_status = QLabel("Press Ctrl+Alt+S to capture and translate, or start live capture.")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # Auto-translate checkbox
        self.chk_auto_translate = QCheckBox("Auto-translate captured text")
        self.chk_auto_translate.setChecked(True)
        self.chk_auto_translate.stateChanged.connect(self._on_auto_translate_toggled)
        layout.addWidget(self.chk_auto_translate)

        # OCR text area
        ocr_label = QLabel("Captured text:")
        ocr_label.setStyleSheet("font-weight: bold; padding-top: 10px;")
        layout.addWidget(ocr_label)

        self.txt_ocr = QTextEdit()
        self.txt_ocr.setReadOnly(False)
        self.txt_ocr.setPlaceholderText("OCR text appears here (Ctrl+Alt+S), or paste characters to translate...")
        self.txt_ocr.setStyleSheet("background: #1e1e1e; color: #d4d4d4; padding: 10px; font-family: monospace;")
        self.txt_ocr.setMinimumHeight(120)
        layout.addWidget(self.txt_ocr)

        # Translation button
        self.btn_translate = QPushButton("Translate")
        self.btn_translate.clicked.connect(self.translate_current_text)
        self.btn_translate.setStyleSheet("padding: 8px; font-size: 12px;")
        layout.addWidget(self.btn_translate)

        # Translation area
        translation_label = QLabel("Translation:")
        translation_label.setStyleSheet("font-weight: bold; padding-top: 10px;")
        layout.addWidget(translation_label)

        self.txt_translation = QTextEdit()
        self.txt_translation.setReadOnly(True)
        self.txt_translation.setPlaceholderText("Translations appear here...")
        self.txt_translation.setStyleSheet("background: #1e1e1e; color: #d4d4d4; padding: 10px; font-family: monospace;")
        self.txt_translation.setMinimumHeight(100)
        layout.addWidget(self.txt_translation)

        # Speak buttons
        speak_row = QWidget()
        speak_layout = QVBoxLayout(speak_row)
        self.btn_speak_ocr = QPushButton("Speak captured text")
        self.btn_speak_ocr.clicked.connect(lambda: self.speak_text(source="ocr"))
        self.btn_speak_translation = QPushButton("Speak translation")
        self.btn_speak_translation.clicked.connect(lambda: self.speak_text(source="translation"))
        speak_layout.addWidget(self.btn_speak_ocr)
        speak_layout.addWidget(self.btn_speak_translation)
        layout.addWidget(speak_row)

    def toggle_sharing(self, checked):
        """Toggle periodic fullscreen capture (live OCR preview)."""
        if checked:
            self.stream_thread = ScreenShareThread(self.ocr_service, interval=5.0)  # 5 second delay between captures
            self.stream_thread.content_update.connect(self.handle_frame)
            self.stream_thread.start()

            self.btn_toggle_share.setText("Stop Fullscreen Capture")
            self.lbl_status.setText("Capturing fullscreen...")
            Logger.info("Started fullscreen capture (5 second interval)")
        else:
            if self.stream_thread:
                self.stream_thread.stop()
                self.stream_thread = None

            self.btn_toggle_share.setText("Start Fullscreen Capture")
            self.lbl_status.setText("Stopped")
            Logger.info("Stopped fullscreen capture")

    def open_live_view(self):
        """Open the OBS-style live window share."""
        if self.live_view is not None and self.live_view.isVisible():
            self.live_view.raise_()
            return

        self.live_view = LiveViewWindow(self.translation_service, self.ocr_service)
        self.live_view.show()
        Logger.info("Live window share opened")

    def pil2pixmap_scaled(self, image):
        """Converts a PIL Image into a scaled QPixmap that fits the preview."""
        return pil2pixmap(image).scaled(self.lbl_preview.width(), self.lbl_preview.height(),
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def resizeEvent(self, event):
        """Re-render the preview at the new size when the window is resized."""
        super().resizeEvent(event)
        if self._last_preview_image is not None:
            self.lbl_preview.setPixmap(self.pil2pixmap_scaled(self._last_preview_image))

    def handle_frame(self, pil_image, extracted_text):
        """Receives the captured image and OCR text from the live capture stream."""
        self._last_preview_image = pil_image
        pixmap = self.pil2pixmap_scaled(pil_image)
        self.lbl_preview.setPixmap(pixmap)

        if extracted_text:
            short_text = extracted_text.replace('\n', ' ')[:60]
            self.lbl_status.setText(f"OCR: {short_text}...")
            Logger.info(f"Extracted text ({len(extracted_text)} chars): {short_text}...")

            if self.chk_auto_translate.isChecked():
                self.show_ocr_text(extracted_text, translate=True)
        else:
            self.lbl_status.setText("No text detected in current frame")

    def show_ocr_text(self, ocr_text: str, translate: bool = True):
        """
        Display OCR-extracted text and optionally translate it.

        Args:
            ocr_text: Text extracted from a screenshot
            translate: Translate immediately after displaying
        """
        if not ocr_text.strip():
            self.lbl_status.setText("No text detected")
            return

        self.txt_ocr.setPlainText(ocr_text)
        if translate:
            self.translate_current_text()

    def translate_current_text(self):
        """Translate whatever is currently in the OCR text box."""
        text = self.txt_ocr.toPlainText().strip()
        if not text:
            self.lbl_status.setText("Nothing to translate")
            return

        if self.translation_worker and self.translation_worker.isRunning():
            Logger.warning("Translation already in progress, skipping new request")
            return

        self.lbl_status.setText("Translating...")
        self.txt_translation.setPlainText("Translating...")

        self.translation_worker = TranslationWorker(self.translation_service, text)
        self.translation_worker.finished.connect(self._on_translation)
        self.translation_worker.error.connect(self._on_translation_error)
        self.translation_worker.start()

    def _on_translation(self, result: dict):
        translation = result.get("translation", "")
        cached = " (cached)" if result.get("cached") else ""
        self.txt_translation.setPlainText(translation)
        self.lbl_status.setText(f"Translated{cached}")
        Logger.info(f"Translation complete: {translation[:60]}...")

    def _on_translation_error(self, error_msg: str):
        Logger.error(f"Translation failed: {error_msg}")
        self.lbl_status.setText(f"Translation error: {error_msg}")
        self.txt_translation.setPlainText(f"Error: {error_msg}")

    def _on_auto_translate_toggled(self):
        Logger.debug(f"Auto-translate: {self.chk_auto_translate.isChecked()}")

    def speak_text(self, source: str = "ocr"):
        """Speak the OCR text or its translation using the TTS engines."""
        text = self.txt_ocr.toPlainText() if source == "ocr" else self.txt_translation.toPlainText()
        text = text.strip()
        if not text:
            self.lbl_status.setText("Nothing to speak")
            return

        self.lbl_status.setText("Synthesizing audio...")
        self.speech.synthesize_async(text, callback=lambda audio: self._on_audio_ready(audio))

    def _on_audio_ready(self, audio):
        """Callback from the TTS worker thread; hands audio bytes to the main thread."""
        if not audio:
            self.play_audio_signal.emit("")
            return

        # Callback runs on the TTS worker thread: only emit a signal, never touch widgets
        mime_type, audio_bytes = audio
        suffix = ".wav" if "wav" in mime_type else ".mp3"
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_bytes)
                audio_path = f.name
            self.play_audio_signal.emit(audio_path)
        except Exception as e:
            Logger.error(f"Failed to write audio file: {e}")
            self.play_audio_signal.emit("")

    def _play_audio_file(self, file_path: str):
        """Play audio from a file path (thread-safe via signal). Empty path marks synthesis failure."""
        if not file_path or not os.path.exists(file_path):
            self.lbl_status.setText("Audio synthesis failed (check logs)")
            return

        self.audio_player.stop()
        self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(os.path.abspath(file_path))))
        self.audio_player.play()
        self.lbl_status.setText("Speaking...")

    def _on_audio_error(self, error):
        """Handle audio playback errors."""
        error_string = self.audio_player.errorString()
        Logger.error(f"Audio playback error: {error} - {error_string}")
        self.lbl_status.setText(f"Audio error: {error_string}")
