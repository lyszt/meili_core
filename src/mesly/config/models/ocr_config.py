"""
OCR configuration dataclass
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class OCRConfig:
    """OCR engine configuration"""
    engine: str = "pytesseract"  # pytesseract (the only wired engine)
    languages: List[str] = field(default_factory=lambda: ["es", "fr", "it", "pt", "ro", "en"])
    confidence_threshold: float = 0.5
    use_gpu: bool = False
