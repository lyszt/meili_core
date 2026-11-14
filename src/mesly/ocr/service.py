"""
OCR service: resolves the tessdata directory and language packs,
then runs Tesseract on captured images.
"""

import os

import numpy as np
import pytesseract
from pytesseract import Output
from pathlib import Path
from PIL import Image, ImageOps

from ..config import ConfigTemplate
from ..utils import Logger
from ..utils.inference import inference_lock

ROOT = Path(__file__).resolve().parents[3]

# Words below this confidence are OCR noise and never reach the card.
# Real subtitle text over video scores much lower than pristine text, so
# this bar is deliberately permissive; the fallback below rescues text
# that dips under it entirely.
MIN_WORD_CONFIDENCE = 40.0

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
        self._rapidocr = self._init_rapidocr()

    def _init_rapidocr(self):
        """Use RapidOCR when available (better for Chinese subtitles)."""
        try:
            from rapidocr_onnxruntime import RapidOCR
            Logger.info("OCR: using RapidOCR engine")
            return RapidOCR()
        except Exception:
            return None

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

    def _preprocess(self, image: Image) -> Image:
        """Preprocess image for subtitle OCR (grayscale, scale, contrast, threshold)."""
        gray = image if image.mode == "L" else image.convert("L")
        # Upscale small crops so strokes are clearer for Tesseract.
        w, h = gray.size
        if h < 64:
            scale = max(2, min(4, -(-64 // max(1, h))))
            gray = gray.resize((w * scale, h * scale), Image.LANCZOS)
        # Boost contrast then binarize with Otsu threshold.
        gray = ImageOps.autocontrast(gray, cutoff=1)
        arr = np.asarray(gray)
        if arr.size:
            hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
            total = arr.size
            sum_total = np.dot(np.arange(256), hist)
            sum_b = 0.0
            w_b = 0.0
            max_var = 0.0
            threshold = 127
            for i in range(256):
                w_b += hist[i]
                if w_b == 0:
                    continue
                w_f = total - w_b
                if w_f == 0:
                    break
                sum_b += i * hist[i]
                m_b = sum_b / w_b
                m_f = (sum_total - sum_b) / w_f
                var_between = w_b * w_f * (m_b - m_f) ** 2
                if var_between > max_var:
                    max_var = var_between
                    threshold = i
            arr = np.where(arr > threshold, 255, 0).astype(np.uint8)
            gray = Image.fromarray(arr, mode="L")
        return gray

    def image_to_text(self, image: Image, psm: int = None) -> str:
        """
        OCR a PIL image using the configured languages.

        Prefers RapidOCR when installed (better for Chinese subtitles),
        otherwise uses Tesseract with preprocessing and PSM fallbacks.
        """
        base_config = f"--psm {psm}" if psm else ""
        with inference_lock:
            if self._rapidocr is not None:
                try:
                    img = np.array(image.convert("RGB"))
                    # RapidOCR expects BGR
                    img = img[:, :, ::-1]
                    result, _ = self._rapidocr(img)
                    if result:
                        texts = [str(item[1]).strip() for item in result
                                 if len(item) > 1 and str(item[1]).strip()]
                        if texts:
                            text = " ".join(texts)
                            Logger.info(f"OCR (RapidOCR): '{text[:60]}'")
                            return text
                except Exception as e:
                    Logger.warning(f"OCR: RapidOCR failed, falling back to Tesseract ({e})")

            processed = None
            if self._tessdata_dir:
                try:
                    processed = self._preprocess(image)
                    # Try LSTM engine with configured psm, then fallback PSMs.
                    psm_candidates = [psm] if psm else [7, 6]
                    seen = set()
                    psm_list = []
                    for p in psm_candidates + [7, 6, 11]:
                        if p not in seen:
                            seen.add(p)
                            psm_list.append(p)
                    best_text = ""
                    best_score = -1.0
                    last_confs = []
                    for p in psm_list:
                        tess_config = f"--oem 1 --psm {p}"
                        data = pytesseract.image_to_data(
                            processed, lang=self.lang, config=tess_config,
                            output_type=Output.DICT)
                        words = []
                        confidences = []
                        for level, text, conf in zip(data["level"], data["text"],
                                                     data["conf"]):
                            if level != 5:
                                continue
                            text = text.strip()
                            if not text:
                                continue
                            try:
                                confidence = float(conf)
                            except (TypeError, ValueError):
                                confidence = -1.0
                            confidences.append(confidence)
                            if confidence >= MIN_WORD_CONFIDENCE:
                                words.append(text)
                        fallback = (not words and confidences
                                    and max(confidences) >= 0)
                        if fallback:
                            words = [t.strip() for lvl, t in zip(data["level"], data["text"])
                                     if lvl == 5 and t.strip()]
                        candidate = " ".join(words)
                        # Score: prefer more text with reasonable confidence.
                        valid_confs = [c for c in confidences if c >= 0]
                        avg_conf = (sum(valid_confs) / len(valid_confs)) if valid_confs else 0.0
                        score = len(candidate) + avg_conf / 100.0
                        if score > best_score:
                            best_score = score
                            best_text = candidate
                            last_confs = confidences
                        # Good enough result, avoid extra passes.
                        if len(candidate) >= 2 and avg_conf >= 45:
                            last_confs = confidences
                            best_text = candidate
                            break
                    if last_confs:
                        Logger.info(
                            f"OCR confidences: {['%.0f' % c for c in last_confs]}")
                    return best_text
                except Exception as e:
                    Logger.error(f"OCR failed with langs '{self.lang}': {e}")

            try:
                if processed is None:
                    processed = self._preprocess(image)
                tess_config = base_config or "--oem 1 --psm 7"
                return pytesseract.image_to_string(processed, config=tess_config).strip()
            except Exception as e:
                Logger.error(f"OCR failed: {e}")
                return ""
