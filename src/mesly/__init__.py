"""
Mesly - OCR-based language learning tool
"""

from .utils import Logger, HotkeyManager
from .capture import ScreenCapture
from .app import MeslyApp

__version__ = "0.2.0"
__author__ = "kaldwin"

__all__ = [
    "Logger",
    "HotkeyManager",
    "ScreenCapture",
    "MeslyApp",
]
