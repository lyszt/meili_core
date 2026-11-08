"""
OCR service: resolves the tessdata directory and language packs,
then runs Tesseract on captured images.
"""

import os
import subprocess

import pytesseract
from pathlib import Path
from PIL import Image

from ..config import ConfigTemplate
from ..utils import Logger

ROOT = Path(__file__).resolve().parents[3]

# config language codes -> Tesseract language codes
LANG_ALIASES = {
    "en": "eng",
    "zh": "chi_sim",
    "zh-cn": "chi_sim",
    "zh-tw": "chi_tra",
    "ja": "jpn",
    "ko": "kor",
    "es": "spa",
    "fr": "fra",
    "it": "ita",
    "pt": "por",
    "ro": "ron",
    "de": "deu",
    "ru": "rus",
}

# Repo-local tessdata (downloaded language packs) takes priority over system
# dirs, followed by common tessdata locations across distributions.
TESSDATA_CANDIDATES = [
    str(ROOT / "data" / "tessdata"),     # vendored in this repo
    "/usr/share/tesseract/tessdata",     # Arch
    "/usr/share/tessdata",               # Arch (alternate)
    "/usr/share/tesseract-ocr/tessdata",  # Debian / Ubuntu
    "/usr/share/tesseract-ocr/4.00/tessdata",  # Debian (older)
    "/usr/local/share/tessdata",         # Manual installs
]


class OcrService:
    """Single entry point for OCR: tessdata resolution + configured languages."""

    def __init__(self, config: ConfigTemplate):
        self.config = config
        self.lang = self._resolve_langs()
        self._tessdata_dir = self._resolve_tessdata()

    def _resolve_langs(self) -> str:
        """Map config language codes to a Tesseract lang string (e.g. 'eng+chi_sim')."""
        configured = getattr(self.config.ocr, "languages", None) or ["en"]
        langs = [LANG_ALIASES.get(str(code).lower(), str(code)) for code in configured]
        deduped = list(dict.fromkeys(langs))
        return "+".join(deduped)

    def _resolve_tessdata(self) -> str:
        """
        Find a tessdata directory containing traineddata files and export
        TESSDATA_PREFIX so the tesseract binary can find it.
        """
        env_dir = os.environ.get("TESSDATA_PREFIX")
        if env_dir and os.path.isdir(env_dir):
            return env_dir

        for candidate in TESSDATA_CANDIDATES:
            if os.path.isdir(candidate):
                # Only useful if it actually contains language files
                if any(name.endswith(".traineddata") for name in os.listdir(candidate)):
                    os.environ["TESSDATA_PREFIX"] = candidate
                    Logger.info(f"OCR: using tessdata at {candidate}")
                    return candidate

        Logger.warning(
            "OCR: no tessdata directory found in TESSDATA_CANDIDATES; "
            "install tesseract language packs (e.g. tesseract-data-eng) "
            "or set TESSDATA_PREFIX"
        )
        return ""

    def image_to_text(self, image: Image) -> str:
        """
        OCR a PIL image using the configured languages.

        Falls back to a bare 'eng' call if anything goes wrong, so a
        half-configured system still returns whatever OCR it can.
        """
        if self._tessdata_dir:
            try:
                return pytesseract.image_to_string(image, lang=self.lang).strip()
            except Exception as e:
                Logger.error(f"OCR failed with langs '{self.lang}': {e}")

        try:
            return pytesseract.image_to_string(image).strip()
        except Exception as e:
            Logger.error(f"OCR failed: {e}")
            return ""
