"""
Shared helpers and background workers for the Mesly windows.
"""

import time

from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication

from ..ocr import OcrService
from ..translation import TranslationService
from ..utils import Logger


def capped_window_size(default_width: int, default_height: int,
                       max_fraction_width: float = 0.5, max_fraction_height: float = 0.8):
    """
    Clamps a default window size to a fraction of the primary screen's
    available geometry, so windows never dwarf small displays.
    """
    geometry = QApplication.primaryScreen().availableGeometry()
    return (
        min(default_width, int(geometry.width() * max_fraction_width)),
        min(default_height, int(geometry.height() * max_fraction_height)),
    )


def pil2pixmap(image):
    """Converts a PIL Image into a QPixmap for Qt display."""
    if image.mode == "RGB":
        r, g, b = image.split()
        image = Image.merge("RGB", (b, g, r))

    im2 = image.convert("RGBA")
    data = im2.tobytes("raw", "BGRA")
    qim = QImage(data, image.size[0], image.size[1], QImage.Format_ARGB32)
    return QPixmap.fromImage(qim)


class TranslationWorker(QThread):
    """Runs translation in a background thread without blocking the GUI."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, translation_service: TranslationService, text: str,
                 from_lang: str = "auto", to_lang: str = "en"):
        super().__init__()
        self.translation_service = translation_service
        self.text = text
        self.from_lang = from_lang
        self.to_lang = to_lang

    def run(self):
        try:
            Logger.info(f"Translation starting: '{self.text[:50]}'")
            result = self.translation_service.translate(
                self.text, from_lang=self.from_lang, to_lang=self.to_lang
            )
            if "error" in result:
                self.error.emit(result.get("translation", result["error"]))
            else:
                self.finished.emit(result)
        except Exception as e:
            Logger.error(f"Translation worker failed: {e}")
            self.error.emit(str(e))


class OcrWorker(QThread):
    """Runs OCR on a PIL image in a background thread without blocking the GUI."""
    ocr_finished = pyqtSignal(str)

    def __init__(self, ocr_service: OcrService, image):
        super().__init__()
        self.ocr_service = ocr_service
        self.image = image

    def run(self):
        try:
            Logger.info("OCR starting")
            t0 = time.perf_counter()
            text = self.ocr_service.image_to_text(self.image)
            Logger.info(f"OCR done in {time.perf_counter() - t0:.2f}s: "
                        f"'{(text or '')[:40]}'")
            self.ocr_finished.emit(text)
        except Exception as e:
            Logger.error(f"OCR worker failed: {e}")
            self.ocr_finished.emit("")
