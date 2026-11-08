"""
HUD overlay: transparent always-on-top translation layer.

On startup it prompts the system window picker once, then the user marks
a watch region on the stream and new Chinese there is OCRed and displayed
with its translation.
"""

import os
import re
import tempfile
import threading

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QApplication, QSizeGrip,
                             QRubberBand, QStyle, QStyleOption, QToolTip)
from PyQt5.QtCore import Qt, QRect, QSize, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QClipboard, QColor, QCursor, QFontMetrics, QPainter, QPen
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

import numpy as np
from PIL import Image

from ..capture import PortalCapture, portal_available
from ..dictionary import CEDict, char_pinyin
from ..ocr import OcrService, cjk_only
from ..translation import TranslationService
from ..tts import SpeechSynthesizer
from ..utils import Logger
from .shared import TranslationWorker, OcrWorker, capped_window_size

BAR_WIDTH_FRACTION = 0.99
BAR_HEIGHT = 690

# Minimum drag size (pixels)
MIN_REGION_SIZE = 24
# Usable text width inside the study card
CARD_TEXT_WIDTH = 640
# Wrap target slightly inside the card so metric drift never reaches the edge
WRAP_WIDTH = CARD_TEXT_WIDTH - 40
# Watch poll interval (seconds)
WATCH_INTERVAL = .5


def wrap_dictionary(entries, max_units=110):
    """Join breakdown entries with explicit line breaks instead of relying
    on wrapped-size hints, which size the card badly. One CJK character
    counts double."""
    def units(item):
        return sum(2 if ord(ch) > 0x2E7F else 1 for ch in item)

    lines = []
    current = ""
    for entry in entries:
        piece = entry if not current else "  ·  " + entry
        if current and units(current) + units(piece) > max_units:
            lines.append(current)
            current = entry
        else:
            current = piece
    if current:
        lines.append(current)
    return "\n".join(lines)


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
            if not self.hud._start_window_drag(QCursor.pos()):
                event.ignore()
            else:
                event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.hud._window_drag_move(QCursor.pos())

    def mouseReleaseEvent(self, event):
        self.hud._end_window_drag()

    def mouseDoubleClickEvent(self, event):
        self.hud._toggle_maximize()


def start_system_move(widget) -> bool:
    """Ask the compositor to drag the window. On Wayland a client cannot
    move its own top-level windows (self.move() is ignored), the drag
    must go through the compositor via startSystemMove."""
    window = widget.window()
    handle = window.windowHandle() if window is not None else None
    if handle is None:
        return False
    try:
        handle.startSystemMove()
        return True
    except Exception:
        return False


def wrap_to_width(text, metrics, max_width):
    """Word-wrap into explicit newlines so the label never depends on
    wrapped-size hints, which size the card badly."""
    words = text.split()
    if not words:
        return text
    lines = []
    current = words[0]
    for word in words[1:]:
        if metrics.horizontalAdvance(current + " " + word) <= max_width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)


def wrap_cjk_to_width(text, metrics, max_width):
    """Char-wrap hanzi (it has no spaces); only inserts breaks when the
    text would not fit on one line."""
    lines = []
    current = ""
    for ch in text:
        if current and metrics.horizontalAdvance(current + ch) > max_width:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return "\n".join(lines)


class CardGrip(QWidget):
    """Drag pill at the top of the study card."""

    def __init__(self, card, parent=None):
        super().__init__(parent)
        self.card = card
        self.setFixedSize(40, 6)
        self.setObjectName("hud_card_grip")
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.card.start_drag(event.globalPos()):
            event.accept()
            return
        super().mousePressEvent(event)


class StudyCard(QWidget):
    """The study text box: a child of the overlay, raised above all other
    overlay elements, drag it anywhere inside the overlay. Dragging a
    child widget is client-side, so this works on Wayland (unlike moving
    the window itself)."""

    def __init__(self, hud, parent=None):
        super().__init__(parent)
        self.hud = hud
        self.setObjectName("hud_card")
        self._drag_offset = None
        self.setCursor(Qt.SizeAllCursor)
        self.setStyleSheet("""
            #hud_card {
                background: rgba(8, 10, 16, 165);
                border-radius: 14px;
                border: 1px solid rgba(255, 255, 255, 26);
            }
            #hud_card_grip {
                background: rgba(255, 255, 255, 70);
                border-radius: 3px;
            }
            #hud_hanzi {
                color: rgba(232, 240, 252, 245);
                font-size: 24px;
                font-weight: 600;
                background: transparent;
            }
            #hud_translation {
                color: #ffffff;
                font-size: 14px;
                font-weight: 500;
                background: transparent;
            }
            #hud_pinyin {
                color: #a8d8ff;
                font-size: 16px;
                background: transparent;
            }
            #hud_dict {
                color: rgba(205, 228, 250, 215);
                font-size: 11px;
                background: transparent;
            }
        """)

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)

    def start_drag(self, global_pos):
        """Start a client-side drag from anywhere; returns True if
        grabbed."""
        if self.parentWidget() is None:
            return False
        self._drag_offset = self.mapFromGlobal(global_pos)
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_drag(event.globalPos()):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            parent = self.parentWidget()
            self.move(parent.mapFromGlobal(event.globalPos()) - self._drag_offset)
            self.hud._card_moved = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None


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
        # Text offset in 8 directions
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (1, -1), (-1, 1), (1, 1)):
            painter.drawText(rect.adjusted(dx, dy, dx, dy), align, text)
        # Main fill
        painter.setPen(QPen(self.palette().color(self.foregroundRole())))
        painter.drawText(rect, align, text)

    def mousePressEvent(self, event):
        # Clicking anywhere on the text drags the study card, so the
        # whole surface is a grab area
        if event.button() == Qt.LeftButton:
            hud = self.window()
            card = getattr(hud, "card", None)
            if card is not None and card.start_drag(event.globalPos()):
                event.accept()
                return
        super().mousePressEvent(event)


class HanziLabel(OutlineLabel):
    """Hanzi line with a per-character hover tooltip: pinyin + gloss."""

    def __init__(self, hud, parent=None):
        super().__init__("", parent)
        self.hud = hud
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):
        self._show_char_tooltip(event.pos(), event.globalPos())
        event.accept()

    def _show_char_tooltip(self, pos, global_pos):
        text = self.text()
        if not text or self.hud is None or self.hud.cedict is None:
            QToolTip.hideText()
            return
        fm = QFontMetrics(self.font())
        width = fm.horizontalAdvance(text)
        # Center-aligned single line: hit-test the character under the tip
        left = (self.contentsRect().width() - width) // 2
        x = pos.x() - left
        if x < 0 or x >= width:
            QToolTip.hideText()
            return
        index = 0
        while (index < len(text) - 1
               and fm.horizontalAdvance(text[:index + 1]) <= x):
            index += 1
        ch = text[index]
        if not re.match(r"[\u3400-\u4dbf\u4e00-\u9fff]", ch):
            QToolTip.hideText()
            return
        if not self.hud.cedict.load():
            QToolTip.hideText()
            return
        entry = self.hud.cedict.lookup(ch)
        if entry is None:
            QToolTip.hideText()
            return
        _, dict_pinyin, glosses = entry
        # CC-CEDICT stores tone numbers (shi4); pypinyin can render this
        # single character with real tone marks instead
        pinyin = char_pinyin(ch) or dict_pinyin
        QToolTip.showText(global_pos,
                          f"{ch}  {pinyin}\n" + "\n".join(glosses[:4]))


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

        # --- Study card: floating always-on-top window with the study text ---
        self.card = StudyCard(self, self)
        self.card.setMinimumSize(320, 70)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(26, 8, 26, 14)
        card_layout.setSpacing(4)
        self._card_moved = False

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 3)
        grip_row.addStretch(1)
        self.card_grip = CardGrip(self.card)
        grip_row.addWidget(self.card_grip)
        grip_row.addStretch(1)
        card_layout.addLayout(grip_row)

        self.pinyin_label = OutlineLabel("")
        self.pinyin_label.setObjectName("hud_pinyin")
        self.pinyin_label.setAlignment(Qt.AlignHCenter)
        card_layout.addWidget(self.pinyin_label)

        self.hanzi_label = HanziLabel(self)
        self.hanzi_label.setObjectName("hud_hanzi")
        self.hanzi_label.setAlignment(Qt.AlignHCenter)
        self.hanzi_label.setText("框选字幕区")
        card_layout.addWidget(self.hanzi_label)

        self.translation_label = OutlineLabel("")
        self.translation_label.setObjectName("hud_translation")
        self.translation_label.setAlignment(Qt.AlignHCenter)
        card_layout.addWidget(self.translation_label)

        self.dict_label = OutlineLabel("")
        self.dict_label.setObjectName("hud_dict")
        self.dict_label.setAlignment(Qt.AlignHCenter)
        card_layout.addWidget(self.dict_label)

        # Fixed text width with manual wrapping: labels can never push the
        # card wider, and size hints stay exact (wordWrap hints size the
        # card badly)
        for label in (self.hanzi_label, self.pinyin_label,
                      self.dict_label, self.translation_label):
            label.setFixedWidth(CARD_TEXT_WIDTH)
            label.setWordWrap(False)

        layout.addStretch(1)
        layout.addLayout(bottom_row)
        self._watch_mark = QWidget(self)
        self._watch_mark.setObjectName("hud_watch_mark")
        self._watch_mark.hide()
        self.watch_stream_rect = None
        self.watch_region = None
        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self)
        self._rubber_origin = None
        self._region_ocr_worker = None
        self._last_watch_region = None

        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_tick)

        self.setStyleSheet("""
            HUDWindow {
                background: transparent;
            }
            #hud_watch_mark {
                border: 1px solid rgba(160, 210, 255, 70);
                border-radius: 3px;
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

        self.cedict = CEDict()
        self._cedict_loader = threading.Thread(
            target=self.cedict.load, daemon=True, name="cedict-load")
        self._cedict_loader.start()

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
        self._sync_card()
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

    def shutdown(self):
        """Stop every thread before exit: a QThread destroyed while
        running aborts the whole process."""
        self._watch_timer.stop()
        if self._region_ocr_worker is not None and self._region_ocr_worker.isRunning():
            self._region_ocr_worker.wait(5000)
        if self.translation_worker is not None and self.translation_worker.isRunning():
            self.translation_worker.wait(5000)
        self.stop_stream()

    def _quit(self):
        self.shutdown()
        QApplication.quit()

    def closeEvent(self, event):
        self.shutdown()
        event.accept()

    # ------------------------------------------------------------------
    # Stream + OCR + translation pipeline
    # ------------------------------------------------------------------

    def _on_stream_status(self, message):
        self.status_label.setText(message)

    def _on_stream_error(self, message):
        self.hanzi_label.setText("Stream stopped")
        self.status_label.setText(message)

    def _display_hanzi(self, hanzi: str, dictionary: bool = True):
        """Show the study layer: hanzi, pinyin, dictionary breakdown."""
        hanzi_fm = self.hanzi_label.fontMetrics()
        self.hanzi_label.setText(
            wrap_cjk_to_width(hanzi, hanzi_fm, WRAP_WIDTH))
        self.pinyin_label.setText(
            wrap_to_width(char_pinyin(hanzi),
                          self.pinyin_label.fontMetrics(), WRAP_WIDTH))
        # The dictionary line is omitted during subtitle watching: hover
        # on any character gives its meaning, and the breakdown clutters
        # a line you are reading in passing
        entries = self.cedict.breakdown(hanzi) if dictionary else []
        self.dict_label.setText(wrap_dictionary(entries))
        self._sync_card()

    def _start_translation(self, hanzi: str):
        if self.translation_worker is not None and self.translation_worker.isRunning():
            return
        self.translation_label.setText("…")
        self.translation_worker = TranslationWorker(self.translation_service, hanzi)
        self.translation_worker.finished.connect(self._on_translation)
        self.translation_worker.error.connect(self._on_translation_error)
        self.translation_worker.start()

    def show_ocr_text(self, ocr_text, image=None, translate=True,
                      dictionary=True):
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
        self._display_hanzi(hanzi, dictionary=dictionary)
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
        self.translation_label.setText(
            wrap_to_width(translation,
                          self.translation_label.fontMetrics(),
                          WRAP_WIDTH))
        self.status_label.setText("Translated")
        self._sync_card()

    def _on_translation_error(self, message):
        self.translation_label.setText(
            wrap_to_width(f"(translation failed: {message})",
                          self.translation_label.fontMetrics(),
                          WRAP_WIDTH))
        self.status_label.setText("Translation error")
        self._sync_card()

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
        self.status_label.setText("Audio error")

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
        """Drag grip handler: maximized windows restore first. The drag
        itself goes through the compositor (Wayland forbids clients
        moving their own windows). Returns True if a drag started."""
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
        return start_system_move(self)

    def _window_drag_move(self, global_pos):
        if self._drag_offset is not None:
            self.move(global_pos - self._drag_offset)

    def _end_window_drag(self):
        self._drag_offset = None

    # ------------------------------------------------------------------
    # Watch region
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        # Left drag draws the watch region right over the live video:
        # nothing is shown or frozen, only a thin rubber band.
        if event.button() == Qt.LeftButton and self._rubber_origin is None:
            self._rubber_origin = event.pos()
            self._rubber_band.setGeometry(QRect(self._rubber_origin, QSize()))
            self._rubber_band.show()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._rubber_origin is not None and event.buttons() & Qt.LeftButton:
            self._rubber_band.setGeometry(
                QRect(self._rubber_origin, event.pos()).normalized())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._rubber_origin is not None:
            rect = QRect(self._rubber_origin, event.pos()).normalized()
            self._rubber_origin = None
            self._rubber_band.hide()
            if rect.width() >= MIN_REGION_SIZE and rect.height() >= MIN_REGION_SIZE:
                self._set_watch_region(rect)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        self._toggle_maximize()
        event.accept()

    def contextMenuEvent(self, event):
        if self.watch_stream_rect is not None:
            self._clear_watch_region()
        event.accept()

    def _set_watch_region(self, rect):
        """Convert the drawn overlay rectangle into stream coordinates.

        The overlay covers the same screen area as the shared window in
        the normal use case (maximized/fullscreen video), so the box the
        user draws over what they see maps onto the stream by the ratio
        of the two sizes.
        """
        frame = self.last_frame
        if frame is None or frame.width < 1:
            self.status_label.setText("Stream not started yet")
            return
        fw, fh = frame.size
        sx = fw / max(1, self.width())
        sy = fh / max(1, self.height())
        self.watch_stream_rect = QRect(
            round(rect.x() * sx), round(rect.y() * sy),
            round(rect.width() * sx), round(rect.height() * sy))
        # Overlay-local rectangle
        self.watch_region = QRect(rect)

        self._watch_mark.setGeometry(self.watch_region.adjusted(-2, -2, 2, 2))
        self._watch_mark.show()
        QTimer.singleShot(2000, self._watch_mark.hide)

        self.status_label.setText("Watching the box - new Chinese inside translates automatically (right-click clears)")
        Logger.info(f"HUD: watch region {rect} -> stream {self.watch_stream_rect}")
        self._last_watch_region = None
        self._watch_timer.start(int(WATCH_INTERVAL * 1000))
        self._watch_tick()

    def _clear_watch_region(self):
        self.watch_stream_rect = None
        self.watch_region = None
        self._last_watch_region = None
        self._watch_mark.hide()
        self._watch_timer.stop()
        self.status_label.setText("Watch cleared")
        Logger.info("HUD: watch region cleared")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_card()
        if self.watch_region is not None:
            self._watch_mark.setGeometry(self.watch_region.adjusted(-2, -2, 2, 2))

    def _sync_card(self):
        """Fit the card to its text. Default: top-center of the overlay;
        after a drag it stays where put, clamped to the overlay."""
        if not self.card.isVisible():
            self.card.show()
        self.card.raise_()
        self.card.adjustSize()
        if not self._card_moved:
            self.card.move(max(0, (self.width() - self.card.width()) // 2), 44)
            return
        x = max(0, min(self.card.x(), self.width() - self.card.width()))
        y = max(0, min(self.card.y(),
                       max(0, self.height() - self.card.height())))
        self.card.move(x, y)

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
        region = gray[y0:y1, x0:x1]

        # Subtitles are static between cuts: skip the whole OCR pass when
        # the region pixels did not change since the last pass
        if self._last_watch_region is not None and np.array_equal(
                region, self._last_watch_region):
            return
        self._last_watch_region = region
        crop = Image.fromarray(np.ascontiguousarray(region))
        # Small subtitle strips read much better at 2x: upscale before
        # handing to tesseract instead of feeding compressed pixel mush
        if crop.height < 96:
            crop = crop.resize((crop.width * 2, crop.height * 2),
                               Image.LANCZOS)

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

        # Watching a subtitle line: card stays lean (hover has the
        # character-level dictionary)
        dictionary = self.watch_stream_rect is None
        self.show_ocr_text(hanzi, dictionary=dictionary)
