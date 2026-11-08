"""
OCR module for text recognition from screen captures
"""

from .filter import cjk_only
from .service import OcrService

__all__ = ["OcrService", "cjk_only"]
