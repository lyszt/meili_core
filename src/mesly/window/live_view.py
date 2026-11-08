"""
Live window share: pick an open window (or fullscreen), get a live preview
with periodic OCR + translation, like a screen-share tool.
"""

import time

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QTextEdit, QComboBox,
                             QSpinBox, QCheckBox)
from PyQt5.QtCore import Qt

from ..capture import (ScreenCapture, WindowLister, WindowCapture,
                       WindowBoxProvider, MonitorBoxProvider,
                       PortalCapture, portal_available)
from ..ocr import OcrService
from ..translation import TranslationService
from ..utils import Logger
from .shared import pil2pixmap, TranslationWorker, OcrWorker, capped_window_size

DEFAULT_FPS = 10
DEFAULT_OCR_INTERVAL = 3.0
FULLSCREEN_ENTRY = "Entire screen"
PORTAL_ENTRY = "Pick window/screen (system dialog)"
# cmb_windows userData sentinels
PORTAL_SOURCE = "portal"
FULLSCREEN_SOURCE = "fullscreen"


class LiveViewWindow(QMainWindow):
    """OBS-style window share: live preview plus live OCR/translate."""

    def __init__(self, translation_service: TranslationService, ocr_service: OcrService):
        super().__init__()
        self.setWindowTitle("Mesly - Live Window Share")
        width, height = capped_window_size(720, 760, 0.6, 0.85)
        self.resize(width, height)

        self.translation_service = translation_service
        self.ocr_service = ocr_service
        self.capture_thread = None      # WindowCapture (X11) or PortalCapture (Wayland)
        self.ocr_worker = None
        self.translation_worker = None
        self.last_frame = None
        self._last_ocr_time = 0.0

        # UI Setup
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Source picker row
        source_row = QWidget()
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)

        source_layout.addWidget(QLabel("Source:"))
        self.cmb_windows = QComboBox()
        self.cmb_windows.setMinimumWidth(300)
        self.cmb_windows.currentIndexChanged.connect(self._on_source_changed)
        source_layout.addWidget(self.cmb_windows, 1)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_windows)
        source_layout.addWidget(self.btn_refresh)
        layout.addWidget(source_row)

        # Settings row
        settings_row = QWidget()
        settings_layout = QHBoxLayout(settings_row)
        settings_layout.setContentsMargins(0, 0, 0, 0)

        settings_layout.addWidget(QLabel("FPS:"))
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(1, 30)
        self.spin_fps.setValue(DEFAULT_FPS)
        self.spin_fps.valueChanged.connect(self._on_source_changed)
        settings_layout.addWidget(self.spin_fps)

        settings_layout.addWidget(QLabel("OCR every (s):"))
        self.spin_ocr_interval = QSpinBox()
        self.spin_ocr_interval.setRange(1, 60)
        self.spin_ocr_interval.setValue(int(DEFAULT_OCR_INTERVAL))
        settings_layout.addWidget(self.spin_ocr_interval)

        self.chk_auto_ocr = QCheckBox("Auto OCR + translate")
        self.chk_auto_ocr.setChecked(True)
        settings_layout.addWidget(self.chk_auto_ocr)

        self.btn_ocr_now = QPushButton("OCR now")
        self.btn_ocr_now.clicked.connect(self._run_ocr)
        settings_layout.addWidget(self.btn_ocr_now)

        settings_layout.addStretch(1)
        layout.addWidget(settings_row)

        # Preview
        self.lbl_preview = QLabel("Live preview")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setStyleSheet("border: 2px dashed #555; background: #222; color: #888;")
        self.lbl_preview.setMinimumSize(480, 240)
        layout.addWidget(self.lbl_preview, 3)
        self._last_frame_scaled = None

        # Status
        self.lbl_status = QLabel("Select a window to start sharing.")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # OCR text
        ocr_label = QLabel("Captured text:")
        ocr_label.setStyleSheet("font-weight: bold; padding-top: 10px;")
        layout.addWidget(ocr_label)

        self.txt_ocr = QTextEdit()
        self.txt_ocr.setReadOnly(True)
        self.txt_ocr.setPlaceholderText("Live OCR text appears here...")
        self.txt_ocr.setStyleSheet("background: #1e1e1e; color: #d4d4d4; padding: 10px; font-family: monospace;")
        self.txt_ocr.setMinimumHeight(80)
        layout.addWidget(self.txt_ocr, 1)

        # Translation
        translation_label = QLabel("Translation:")
        translation_label.setStyleSheet("font-weight: bold; padding-top: 10px;")
        layout.addWidget(translation_label)

        self.txt_translation = QTextEdit()
        self.txt_translation.setReadOnly(True)
        self.txt_translation.setPlaceholderText("Live translation appears here...")
        self.txt_translation.setStyleSheet("background: #1e1e1e; color: #d4d4d4; padding: 10px; font-family: monospace;")
        self.txt_translation.setMinimumHeight(80)
        layout.addWidget(self.txt_translation, 1)

        # Start
        self.refresh_windows()

    def refresh_windows(self):
        """Reload the open-window list (portal entry, wmctrl/xdotool windows)."""
        self.cmb_windows.blockSignals(True)
        self.cmb_windows.clear()

        if portal_available():
            self.cmb_windows.addItem(PORTAL_ENTRY, PORTAL_SOURCE)
        self.cmb_windows.addItem(FULLSCREEN_ENTRY, FULLSCREEN_SOURCE)

        windows = WindowLister.list_windows()
        if not windows:
            Logger.debug("Live share: no windows listed (wmctrl/xdotool missing, or Wayland)")
        for window in windows:
            self.cmb_windows.addItem(window["title"], window)
        self.cmb_windows.blockSignals(False)

        self._on_source_changed()

    def _on_source_changed(self):
        """Restart the capture thread with the current source and FPS."""
        self._stop_capture()

        source = self.cmb_windows.currentData()
        fps = self.spin_fps.value()

        if source == PORTAL_SOURCE:
            self.capture_thread = PortalCapture()
            self.capture_thread.frame.connect(self._on_frame)
            self.capture_thread.error.connect(self._on_source_error)
            self.capture_thread.start()
            self.lbl_status.setText("Waiting for you to pick a source in the system dialog...")
            Logger.info("Live share started via portal")
            return

        if source == FULLSCREEN_SOURCE or source is None:
            provider = MonitorBoxProvider(ScreenCapture())
            source_name = FULLSCREEN_ENTRY
        else:
            provider = WindowBoxProvider(source)
            source_name = source["title"]

        self.capture_thread = WindowCapture(provider, fps=fps)
        self.capture_thread.frame.connect(self._on_frame)
        self.capture_thread.lost.connect(self._on_source_lost)
        self.capture_thread.start()

        self.lbl_status.setText(f"Sharing: {source_name}")
        Logger.info(f"Live share started: {source_name} @ {fps} FPS")

    def _on_source_error(self, error_msg: str):
        self.lbl_status.setText(error_msg)

    def _on_frame(self, image):
        """Receive a live frame: update preview and maybe trigger OCR."""
        self.last_frame = image
        self._set_preview(image)

        if (self.chk_auto_ocr.isChecked()
                and time.monotonic() - self._last_ocr_time >= self.spin_ocr_interval.value()):
            self._run_ocr()

    def _set_preview(self, image):
        """Scale the frame to the current preview size and display it."""
        self._last_frame_scaled = pil2pixmap(image)
        self._refresh_preview()

    def _refresh_preview(self):
        if self._last_frame_scaled is not None:
            scaled = self._last_frame_scaled.scaled(
                self.lbl_preview.width(), self.lbl_preview.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_preview.setPixmap(scaled)

    def resizeEvent(self, event):
        """Re-render the preview at the new size when the window is resized."""
        super().resizeEvent(event)
        self._refresh_preview()

    def _run_ocr(self):
        """OCR the latest frame, then translate the result."""
        if self.last_frame is None:
            return
        if self.ocr_worker and self.ocr_worker.isRunning():
            return

        self._last_ocr_time = time.monotonic()
        self.ocr_worker = OcrWorker(self.ocr_service, self.last_frame)
        self.ocr_worker.ocr_finished.connect(self._on_ocr_finished)
        self.ocr_worker.start()

    def _on_ocr_finished(self, text: str):
        if not text:
            self.lbl_status.setText("OCR: no text in frame")
            return

        self.txt_ocr.setPlainText(text)
        self.lbl_status.setText("Translating...")

        if self.translation_worker and self.translation_worker.isRunning():
            return

        self.translation_worker = TranslationWorker(self.translation_service, text)
        self.translation_worker.finished.connect(self._on_translation)
        self.translation_worker.error.connect(self._on_translation_error)
        self.translation_worker.start()

    def _on_translation(self, result: dict):
        self.txt_translation.setPlainText(result.get("translation", ""))
        self.lbl_status.setText("Translated")

    def _on_translation_error(self, error_msg: str):
        self.lbl_status.setText(f"Translation error: {error_msg}")
        self.txt_translation.setPlainText(f"Error: {error_msg}")

    def _on_source_lost(self):
        self.lbl_status.setText("Source window closed or not capturable")

    def _stop_capture(self):
        if self.capture_thread:
            if isinstance(self.capture_thread, PortalCapture):
                self.capture_thread.stop()
                self.capture_thread.wait(3000)
            else:
                self.capture_thread.stop()
            self.capture_thread = None

    def closeEvent(self, event):
        """Stop the capture stream and workers when the window is closed."""
        self._stop_capture()
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.wait(2000)
        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.wait(2000)
        Logger.info("Live window share closed")
        event.accept()
