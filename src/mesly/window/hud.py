"""
HUD overlay: transparent always-on-top translation layer.

On startup it prompts the system window picker once, then the user marks
a watch region on the stream and new Chinese there is OCRed and displayed
with its translation.
"""

import os
import tempfile
import threading

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QApplication, QSizeGrip,
                             QRubberBand)
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QClipboard, QColor, QCursor, QPainter, QPen
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

import numpy as np
from PIL import Image

from ..capture import PortalCapture, portal_available
from ..dictionary import CEDict, char_pinyin
from ..ocr import OcrService, cjk_only
from ..translation import TranslationService
from ..tts import SpeechSynthesizer
from ..utils import Logger
from .shared import TranslationWorker, OcrWorker, capped_window_size, pil2pixmap

# Window size caps (bar height is a fallback; the HUD starts maximized)
BAR_WIDTH_FRACTION = 0.99
BAR_HEIGHT = 690

# Minimum watch region size (pixels, stream space)
MIN_REGION_SIZE = 24
# Watch region poll interval (seconds); chi_sim OCR dominates the cycle
WATCH_INTERVAL = 3.0
# Distance between the watch region top and the text block
TEXT_REGION_GAP = 10
# Default lift of the text block from the bottom edge
DEFAULT_TEXT_LIFT = 36


class DragGrip(QWidget):
    """Small chrome widget: drag it to move the HUD, double-click to
    maximize/restore."""

    def __init__(self, hud, parent=None):
        super().__init__(parent)
        self.hud = hud
        self.setFixedSize(QSize(34, 26))
        self.setToolTip("Drag to move (double-click: maximize/restore)")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.hud._start_window_drag(QCursor.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.hud._window_drag_move(QCursor.pos())

    def mouseReleaseEvent(self, event):
        self.hud._end_window_drag()

    def mouseDoubleClickEvent(self, event):
        self.hud._toggle_maximize()


class OutlineLabel(QLabel):
    """
    QLabel that paints its text with a black outline (subtitle style).
    QGraphicsDropShadowEffect cannot be used: graphic effects on
    translucent windows smear ghost copies of the text on Wayland.
    """

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        text = self.text()
        if not text:
            return
        rect = self.contentsRect()
        align = int(self.alignment())
        font = self.font()
        painter.setFont(font)
        pen = QPen(QColor(0, 0, 0, 220))
        painter.setPen(pen)
        # Outline: draw the text offset in 8 directions
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (1, -1), (-1, 1), (1, 1)):
            painter.drawText(rect.adjusted(dx, dy, dx, dy), align, text)
        # Main fill
        painter.setPen(QPen(self.palette().color(self.foregroundRole())))
        painter.drawText(rect, align, text)


class StreamPicker(QWidget):
    """Frozen stream frame the user draws the watch region on. The region
    is returned in stream coordinates, so it never depends on where the
    overlay or window sits on screen.

    Signals:
        picked(stream_rect, scale, panel_top_left_global)
        cancelled()
    """

    picked = pyqtSignal(object, object, object)
    cancelled = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("hud_picker")
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setGeometry(0, 0, 1, 1)
        self._rubber = QRubberBand(QRubberBand.Rectangle, self)
        self._rubber.hide()
        self._origin = None
        self._scale = 1.0
        self.setStyleSheet("""
            #hud_picker {
                background: rgba(10, 12, 16, 140);
            }
        """)

    def freeze(self, frame) -> bool:
        """Show the given PIL frame scaled to fit; False if there is none."""
        if frame is None:
            return False
        parent = self.parentWidget()
        if parent is None:
            return False
        parent_geo = parent.geometry()
        max_w = max(200, int(parent_geo.width() * 0.72))
        max_h = max(150, int(parent_geo.height() * 0.72))
        pixmap = pil2pixmap(frame)
        if pixmap.width() < 10:
            return False
        scaled = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        self._scale = scaled.width() / pixmap.width()
        self.image_label.setPixmap(scaled)
        self.setGeometry(QRect(
            parent_geo.center().x() - scaled.width() // 2,
            parent_geo.center().y() - scaled.height() // 2,
            scaled.width(), scaled.height()))
        self.image_label.setGeometry(self.rect())
        self.show()
        self.raise_()
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._origin is None:
            self._origin = event.pos()
            self._rubber.setGeometry(QRect(self._origin, QSize()))
            self._rubber.show()
            event.accept()
        elif event.button() == Qt.RightButton:
            self.cancelled.emit()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is not None and event.buttons() & Qt.LeftButton:
            self._rubber.setGeometry(
                QRect(self._origin, event.pos()).normalized())
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._origin is not None and event.button() == Qt.LeftButton:
            rect = QRect(self._origin, event.pos()).normalized()
            self._origin = None
            self._rubber.hide()
            if rect.width() >= MIN_REGION_SIZE and rect.height() >= MIN_REGION_SIZE:
                stream_rect = QRect(
                    round(rect.x() / self._scale),
                    round(rect.y() / self._scale),
                    round(rect.width() / self._scale),
                    round(rect.height() / self._scale))
                self.picked.emit(
                    stream_rect, self._scale,
                    self.parentWidget().mapToGlobal(self.pos()))
            else:
                self.cancelled.emit()
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()


class HUDWindow(QWidget):
    """Translucent overlay window with the capture pipeline attached."""

    play_audio_signal = pyqtSignal(str)

    def __init__(self, translation_service: TranslationService, speech: SpeechSynthesizer,
                 ocr_service: OcrService):
        super().__init__()

        self.translation_service = translation_service
        self.speech = speech
        self.ocr_service = ocr_service

        self.capture_thread = None
        self.translation_worker = None
        self.last_frame = None
        self.last_hanzi = ""
        self.last_translation = ""

        self.audio_player = QMediaPlayer()
        self.audio_player.error.connect(self._on_audio_error)
        self.play_audio_signal.connect(self._play_audio_file)

        # Frameless, always on top, no taskbar entry
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        width, height = capped_window_size(1024, 720, 0.99, 0.95)
        self.resize(width, height)

        # Controls on top, text block bottom-center, resize grip corner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 16)
        layout.setSpacing(0)

        # --- Top chrome: drag grip + status + window controls ---
        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(4, 0, 4, 0)
        header_row.setSpacing(6)

        self.drag_grip = DragGrip(self)
        self.drag_grip.setObjectName("hud_grip")
        header_row.addWidget(self.drag_grip)

        self.status_label = QLabel("Pick the window to share, then drag on the overlay to mark the subtitles")
        self.status_label.setObjectName("hud_status")
        header_row.addWidget(self.status_label, 1)
        self.btn_speak_hanzi = QPushButton("音")
        self.btn_speak_hanzi.setToolTip("Speak the captured Chinese")
        self.btn_speak_hanzi.clicked.connect(lambda: self.speak_text("hanzi"))
        self.btn_speak_translation = QPushButton("EN")
        self.btn_speak_translation.setToolTip("Speak the translation")
        self.btn_speak_translation.clicked.connect(lambda: self.speak_text("translation"))
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(self.stop_stream)
        self.btn_max = QPushButton("□")
        self.btn_max.setObjectName("hud_max")
        self.btn_max.setToolTip("Maximize / restore")
        self.btn_max.clicked.connect(self._toggle_maximize)
        self.btn_quit = QPushButton("×")
        self.btn_quit.setToolTip("Quit")
        self.btn_quit.clicked.connect(self._quit)
        for button in (self.btn_speak_hanzi, self.btn_speak_translation,
                       self.btn_stop, self.btn_max, self.btn_quit):
            header_row.addWidget(button)
        layout.addWidget(header)
        self.header = header

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        self.size_grip = QSizeGrip(self)
        bottom_row.addWidget(self.size_grip)
        layout.addLayout(bottom_row)

        # --- Center is empty transparency ---
        layout.addStretch(1)

        # --- Bottom: hanzi + pinyin + breakdown + translation, bottom-center ---
        text_block = QWidget()
        text_layout = QVBoxLayout(text_block)
        text_layout.setContentsMargins(48, 0, 48, 0)
        text_layout.setSpacing(2)

        self.hanzi_label = OutlineLabel("框选字幕区")
        self.hanzi_label.setObjectName("hud_hanzi")
        self.hanzi_label.setWordWrap(True)
        self.hanzi_label.setAlignment(Qt.AlignHCenter)
        text_layout.addWidget(self.hanzi_label)

        # Pinyin + dictionary breakdown are always shown (this app is the
        # study mode)
        self.pinyin_label = OutlineLabel("")
        self.pinyin_label.setObjectName("hud_pinyin")
        self.pinyin_label.setWordWrap(True)
        self.pinyin_label.setAlignment(Qt.AlignHCenter)
        text_layout.addWidget(self.pinyin_label)

        self.dict_label = OutlineLabel("")
        self.dict_label.setObjectName("hud_dict")
        self.dict_label.setWordWrap(True)
        self.dict_label.setAlignment(Qt.AlignHCenter)
        text_layout.addWidget(self.dict_label)

        self.translation_label = OutlineLabel("")
        self.translation_label.setObjectName("hud_translation")
        self.translation_label.setWordWrap(True)
        self.translation_label.setAlignment(Qt.AlignHCenter)
        text_layout.addWidget(self.translation_label)

        text_row = QHBoxLayout()
        text_row.addStretch(1)
        text_row.addWidget(text_block)
        text_row.addStretch(1)
        layout.addLayout(text_row)
        self.text_block = text_block

        # Keeps the text off the bottom edge and above the watch region
        self._lift_spacer = QWidget()
        self._lift_spacer.setFixedHeight(DEFAULT_TEXT_LIFT)
        layout.addWidget(self._lift_spacer)

        # Marker over the designated area; watch_rect is stored in stream
        # coordinates, this screen rectangle only positions the marker
        # and the text lift
        self._watch_mark = QWidget(self)
        self._watch_mark.setObjectName("hud_watch_mark")
        self._watch_mark.hide()
        self.watch_stream_rect = None
        self.watch_region = None

        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_tick)

        self.setStyleSheet("""
            HUDWindow {
                background: transparent;
            }
            #hud_hanzi {
                color: #ffffff;
                font-size: 24px;
                font-weight: 600;
                background: transparent;
            }
            #hud_translation {
                color: #bfe8ff;
                font-size: 16px;
                background: transparent;
            }
            #hud_pinyin {
                color: rgba(255, 255, 255, 245);
                font-size: 13px;
                background: transparent;
            }
            #hud_dict {
                color: rgba(230, 248, 255, 235);
                font-size: 12px;
                background: transparent;
            }
            #hud_watch_mark {
                border: 2px solid rgba(140, 200, 255, 190);
                border-radius: 4px;
                background: transparent;
            }
            #hud_status {
                color: rgba(255, 255, 255, 210);
                font-size: 11px;
                background: transparent;
            }
            QPushButton {
                background: rgba(255, 255, 255, 0);
                color: rgba(255, 255, 255, 200);
                border: none;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 45);
                color: #fff;
            }
        """)

        self._drag_offset = None
        self._normal_geometry = None
        self._frame_picker = None
        self._region_ocr_worker = None

        # CEDICT parse is slow: load in the background
        self.cedict = CEDict()
        self._cedict_loader = threading.Thread(
            target=self.cedict.load, daemon=True, name="cedict-load")
        self._cedict_loader.start()

        # Translations only happen on explicit intent: a selection change
        # or the watch region. The primary selection is sticky (it holds
        # the last thing selected anywhere), so the first signal at
        # startup is the compositor's greeting, not a user action.
        self._last_selection = ""
        self._selection_signals_seen = 0
        QApplication.clipboard().selectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if not self.isMaximized() and self._normal_geometry is None:
            self.showMaximized()
        if not portal_available():
            self.status_label.setText("Portal unavailable (install python-gobject, gst-plugin-pipewire)")
            return
        self._start_capture()

    def _start_capture(self):
        if self.capture_thread is not None:
            return
        self.capture_thread = PortalCapture()
        self.capture_thread.frame.connect(self._on_frame)
        self.capture_thread.error.connect(self._on_stream_error)
        self.capture_thread.status.connect(self._on_stream_status)
        self.capture_thread.start()

    def stop_stream(self):
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread.wait(3000)
            self.capture_thread = None
        self.status_label.setText("Stopped")

    def _quit(self):
        self.stop_stream()
        QApplication.quit()

    def closeEvent(self, event):
        self.stop_stream()
        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.wait(2000)
        if self.speech:
            self.speech.close()
        event.accept()

    # ------------------------------------------------------------------
    # Stream + OCR + translation pipeline
    # ------------------------------------------------------------------

    def _on_stream_status(self, message):
        self.status_label.setText(message)

    def _on_stream_error(self, message):
        self.hanzi_label.setText("Stream stopped")
        self.status_label.setText(message)

    def _display_hanzi(self, hanzi: str):
        """Show the study layer: hanzi, pinyin, dictionary breakdown."""
        self.hanzi_label.setText(hanzi)
        self.pinyin_label.setText(char_pinyin(hanzi))
        dictionary_lines = self.cedict.breakdown(hanzi)
        self.dict_label.setText("  ·  ".join(dictionary_lines))

    def _start_translation(self, hanzi: str):
        if self.translation_worker is not None and self.translation_worker.isRunning():
            return
        self.translation_label.setText("…")
        self.translation_worker = TranslationWorker(self.translation_service, hanzi)
        self.translation_worker.finished.connect(self._on_translation)
        self.translation_worker.error.connect(self._on_translation_error)
        self.translation_worker.start()

    def show_ocr_text(self, ocr_text, image=None, translate=True):
        """
        Entry point for the hotkey capture: display captured Chinese and
        translate. Manual, user-initiated - never automatic.
        """
        if not ocr_text.strip():
            self.status_label.setText("No text detected")
            return

        hanzi = cjk_only(ocr_text)
        if not hanzi:
            self.status_label.setText("No Chinese characters in capture")
            return

        self.last_hanzi = hanzi
        self._display_hanzi(hanzi)
        if translate:
            self._start_translation(hanzi)

    def _on_frame(self, image):
        # Nothing auto-translates on frames; they only feed the picker
        # and the watch region
        self.last_frame = image

    def _on_selection_changed(self):
        """Translate a new primary-selection if it contains Chinese.
        The first signal is the compositor's sticky-selection greeting,
        not a user action - swallow it so opening the app is silent."""
        self._selection_signals_seen += 1
        if self._selection_signals_seen == 1:
            try:
                self._last_selection = (QApplication.clipboard()
                                        .text(mode=QClipboard.Selection) or "")
            except Exception:
                self._last_selection = ""
            return

        try:
            selection = QApplication.clipboard().text(mode=QClipboard.Selection)
        except Exception:
            return

        if not selection or selection == self._last_selection:
            return
        self._last_selection = selection

        hanzi = cjk_only(selection)
        if not hanzi:
            return

        self.last_hanzi = hanzi
        self._display_hanzi(hanzi)
        self.status_label.setText("Translating selection…")
        self._start_translation(hanzi)

    def _on_translation(self, result):
        translation = result.get("translation", "")
        self.last_translation = translation
        self.translation_label.setText(translation)
        self.status_label.setText("Translated")

    def _on_translation_error(self, message):
        self.translation_label.setText(f"(translation failed: {message})")
        self.status_label.setText("Translation error")

    # ------------------------------------------------------------------
    # Speech
    # ------------------------------------------------------------------

    def speak_text(self, which):
        text = self.last_hanzi if which == "hanzi" else self.last_translation
        text = text.strip()
        if not text:
            self.status_label.setText("Nothing to speak")
            return
        self.speech.synthesize_async(text, callback=lambda audio: self._on_audio_ready(audio))

    def _on_audio_ready(self, audio):
        # Runs on the TTS worker thread: only emit a signal, never touch widgets
        if not audio:
            self.play_audio_signal.emit("")
            return
        mime_type, audio_bytes = audio
        suffix = ".wav" if "wav" in mime_type else ".mp3"
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_bytes)
            self.play_audio_signal.emit(f.name)
        except Exception as e:
            Logger.error(f"Failed to write audio file: {e}")
            self.play_audio_signal.emit("")

    def _play_audio_file(self, file_path):
        if not file_path or not os.path.exists(file_path):
            self.status_label.setText("Audio synthesis failed")
            return
        self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(os.path.abspath(file_path))))
        self.audio_player.play()
        self.status_label.setText("Speaking…")

    def _on_audio_error(self, error):
        Logger.error(f"Audio playback error: {error}")
        self.status_label.setText(f"Audio error")

    # ------------------------------------------------------------------
    # Window chrome: drag, maximize, restore
    # ------------------------------------------------------------------

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
            self.btn_max.setText("□")
        else:
            self._normal_geometry = self.geometry()
            self.showMaximized()
            self.btn_max.setText("❐")

    def _start_window_drag(self, global_pos):
        """Drag grip handler: maximized windows restore then follow."""
        if self.isMaximized():
            if self._normal_geometry is None:
                self._normal_geometry = QRect(global_pos.x() - 400,
                                              global_pos.y() - 20, 1000, 700)
            proposed = QRect(global_pos.x() - self._normal_geometry.width() // 2,
                             max(0, global_pos.y() - 20),
                             self._normal_geometry.width(),
                             self._normal_geometry.height())
            self.showNormal()
            self.setGeometry(proposed)
            self.btn_max.setText("□")
        self._drag_offset = global_pos - self.frameGeometry().topLeft()

    def _window_drag_move(self, global_pos):
        if self._drag_offset is not None:
            self.move(global_pos - self._drag_offset)

    def _end_window_drag(self):
        self._drag_offset = None

    # ------------------------------------------------------------------
    # Watch region
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._open_stream_picker()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        self._toggle_maximize()
        event.accept()

    def contextMenuEvent(self, event):
        if self.watch_stream_rect is not None:
            self._clear_watch_region()
        event.accept()

    def _open_stream_picker(self):
        if self.last_frame is None:
            self.status_label.setText("Stream not started yet - pick a window in the system dialog first")
            return
        if self._frame_picker is None:
            self._frame_picker = StreamPicker(self)
            self._frame_picker.picked.connect(self._on_region_picked)
            self._frame_picker.cancelled.connect(self._on_picker_cancelled)
        if self._frame_picker.freeze(self.last_frame):
            self.status_label.setText("Draw a box over the subtitles (right-click / Esc to cancel)")
        else:
            self.status_label.setText("No frame available from the stream yet")
        self._frame_picker.setFocus()

    def _on_picker_cancelled(self):
        if self._frame_picker is not None:
            self._frame_picker.hide()
        self.status_label.setText("Pick cancelled")

    def _on_region_picked(self, stream_rect, scale, panel_top_global):
        """Store the stream-space rect, mark its screen position, watch."""
        if self._frame_picker is not None:
            self._frame_picker.hide()
        self.watch_stream_rect = QRect(stream_rect)

        # Screen rectangle for the marker and text lift only; scaling
        # can shift it, which is acceptable for pure visuals
        screen_top = panel_top_global + QPoint(
            round(stream_rect.x() * scale), round(stream_rect.y() * scale))
        self.watch_region = QRect(
            screen_top,
            QSize(round(stream_rect.width() * scale),
                  round(stream_rect.height() * scale)))
        local_top = self.mapFromGlobal(screen_top)
        self._watch_mark.setGeometry(
            QRect(local_top, self.watch_region.size()).adjusted(-2, -2, 2, 2))
        self._watch_mark.show()
        self._update_lift()

        self.status_label.setText("Watching region - new Chinese there translates automatically (right-click to clear)")
        Logger.info(f"HUD: watch region set at stream {stream_rect}")
        self._watch_timer.start(int(WATCH_INTERVAL * 1000))
        self._watch_tick()

    def _clear_watch_region(self):
        self.watch_stream_rect = None
        self.watch_region = None
        self._watch_mark.hide()
        self._lift_spacer.setFixedHeight(DEFAULT_TEXT_LIFT)
        self._watch_timer.stop()
        if self._frame_picker is not None and self._frame_picker.isVisible():
            self._frame_picker.hide()
        self.status_label.setText("Watch cleared")
        Logger.info("HUD: watch region cleared")

    def _update_lift(self):
        """Push the centered text block above the watch region."""
        if self.watch_region is None:
            self._lift_spacer.setFixedHeight(DEFAULT_TEXT_LIFT)
            return
        region_top_local = self.mapFromGlobal(self.watch_region.topLeft()).y()
        needed = self.height() - region_top_local + TEXT_REGION_GAP
        self._lift_spacer.setFixedHeight(
            max(DEFAULT_TEXT_LIFT, min(needed, self.height() // 2)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_lift()
        self._recenter_watch_mark()

    def _recenter_watch_mark(self):
        if self.watch_region is not None:
            top_left = self.mapFromGlobal(self.watch_region.topLeft())
            self._watch_mark.setGeometry(
                QRect(top_left, self.watch_region.size()).adjusted(-2, -2, 2, 2))

    def _watch_tick(self):
        """Periodic pass over the designated region: crop the latest
        stream frame, OCR it, and translate only when the Chinese
        content changed."""
        if self.watch_stream_rect is None or self.last_frame is None:
            return
        if self._region_ocr_worker is not None and self._region_ocr_worker.isRunning():
            return

        rect = self.watch_stream_rect
        gray = np.asarray(self.last_frame.convert("L"))
        x0 = max(0, min(rect.x(), gray.shape[1] - 1))
        y0 = max(0, min(rect.y(), gray.shape[0] - 1))
        x1 = max(x0 + 1, min(rect.x() + rect.width(), gray.shape[1]))
        y1 = max(y0 + 1, min(rect.y() + rect.height(), gray.shape[0]))
        crop = Image.fromarray(np.ascontiguousarray(gray[y0:y1, x0:x1]))

        self.status_label.setText("Reading region…")
        self._region_ocr_worker = OcrWorker(self.ocr_service, crop)
        self._region_ocr_worker.ocr_finished.connect(self._on_region_ocr_finished)
        self._region_ocr_worker.start()

    def _on_region_ocr_finished(self, text):
        hanzi = cjk_only(text) if text else ""
        if not hanzi:
            if self.watch_stream_rect is not None:
                self.status_label.setText("No Chinese in region")
            else:
                self.hanzi_label.setText("")
                self.status_label.setText("No text in region")
            return

        if self.watch_stream_rect is not None and hanzi == self.last_hanzi:
            self.status_label.setText("Unchanged")
            return

        self.show_ocr_text(hanzi)
