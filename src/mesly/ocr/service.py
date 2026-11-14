"""
OCR service: resolves the tessdata directory and language packs,
then runs Tesseract on captured images.
"""

import hashlib
import os
import re
import threading

import numpy as np
import pytesseract
from pytesseract import Output
from pathlib import Path
from PIL import Image, ImageOps

from ..config import ConfigTemplate
from ..utils import Logger
from ..utils.inference import ocr_lock

ROOT = Path(__file__).resolve().parents[3]

MIN_WORD_CONFIDENCE = 40.0
_HAS_HANZI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

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

TESSDATA_CANDIDATES = [
    str(ROOT / "data" / "tessdata"),
    "/usr/share/tesseract/tessdata",
    "/usr/share/tessdata",
    "/usr/share/tesseract-ocr/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/local/share/tessdata",
]


class OcrService:
    """Single entry point for OCR: tessdata resolution + configured languages."""

    def __init__(self, config: ConfigTemplate):
        self.config = config
        self.lang = self._resolve_langs()
        self._tessdata_dir = self._resolve_tessdata()
        self._rapidocr = self._init_rapidocr()
        self._cache = {}
        self._cache_lock = threading.Lock()

    def _init_rapidocr(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception:
            return None

        providers = self._available_providers()
        if "CUDAExecutionProvider" in providers:
            for kwargs in (
                {"det_use_cuda": True, "cls_use_cuda": True, "rec_use_cuda": True},
                {"providers": ["CUDAExecutionProvider", "CPUExecutionProvider"]},
            ):
                try:
                    engine = RapidOCR(**kwargs)
                    Logger.info("OCR: using RapidOCR engine (CUDA)")
                    return engine
                except Exception:
                    continue
        if "VulkanExecutionProvider" in providers:
            try:
                engine = RapidOCR(providers=["VulkanExecutionProvider", "CPUExecutionProvider"])
                Logger.info("OCR: using RapidOCR engine (Vulkan)")
                return engine
            except Exception:
                pass

        Logger.info("OCR: using RapidOCR engine (CPU)")
        try:
            return RapidOCR()
        except Exception:
            return None

    def _available_providers(self):
        try:
            import onnxruntime as ort
            return ort.get_available_providers()
        except Exception:
            return []

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
        w, h = gray.size
        if h < 48:
            scale = max(2, min(3, -(-48 // max(1, h))))
            gray = gray.resize((w * scale, h * scale), Image.BILINEAR)
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

    def _tesseract_best(self, image: Image, psm: int = None):
        base_config = f"--psm {psm}" if psm else ""
        processed = None
        if self._tessdata_dir:
            try:
                processed = self._preprocess(image)
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
                    valid_confs = [c for c in confidences if c >= 0]
                    avg_conf = (sum(valid_confs) / len(valid_confs)) if valid_confs else 0.0
                    hanzi_bonus = 1.5 if _HAS_HANZI.search(candidate or "") else 0.0
                    score = len(candidate) + avg_conf / 100.0 + hanzi_bonus
                    if score > best_score:
                        best_score = score
                        best_text = candidate
                        last_confs = confidences
                    if len(candidate) >= 2 and avg_conf >= 45 and _HAS_HANZI.search(candidate):
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

    def _cache_key(self, image: Image, psm):
        try:
            data = image.tobytes()
        except Exception:
            data = image.convert("RGB").tobytes()
        digest = hashlib.md5(data).hexdigest()
        return (digest, image.size, image.mode, self.lang, psm)

    def image_to_text(self, image: Image, psm: int = None) -> str:
        """OCR a PIL image, preferring results that contain Chinese text."""
        key = self._cache_key(image, psm)
        with self._cache_lock:
            cached = self._cache.get(key)
        if cached is not None:
            Logger.info("OCR: cache hit")
            return cached

        with ocr_lock:
            with self._cache_lock:
                cached = self._cache.get(key)
            if cached is not None:
                Logger.info("OCR: cache hit")
                return cached
            rapid_text = ""
            if self._rapidocr is not None:
                try:
                    img = np.array(image.convert("RGB"))
                    img = img[:, :, ::-1]
                    result, _ = self._rapidocr(img)
                    if result:
                        texts = [str(item[1]).strip() for item in result
                                 if len(item) > 1 and str(item[1]).strip()]
                        if texts:
                            rapid_text = " ".join(texts)
                            Logger.info(f"OCR (RapidOCR): '{rapid_text[:60]}'")
                            if _HAS_HANZI.search(rapid_text):
                                with self._cache_lock:
                                    if len(self._cache) >= 256:
                                        self._cache.pop(next(iter(self._cache)))
                                    self._cache[key] = rapid_text
                                return rapid_text
                except Exception as e:
                    Logger.warning(f"OCR: RapidOCR failed ({e})")

            tess_text = self._tesseract_best(image, psm=psm)
            if tess_text and _HAS_HANZI.search(tess_text):
                result_text = tess_text
            elif rapid_text:
                result_text = rapid_text
            else:
                result_text = tess_text or ""
            with self._cache_lock:
                if len(self._cache) >= 256:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = result_text
            return result_text
