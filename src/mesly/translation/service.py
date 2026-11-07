"""
Translation service using local Helsinki-NLP (MarianMT) models.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

from transformers import pipeline

from ..utils import Logger

DEFAULT_MODEL = "Helsinki-NLP/opus-mt-mul-en"
CACHE_TTL_SECONDS = 10


class TranslationService:
    """Loads the local MarianMT model and translates text to English."""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self.pipeline = None
        self.loading = True
        self.load_error: Optional[str] = None
        self._cache: Dict[str, Dict] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="translation")
        self._executor.submit(self._load_model)

    def _load_model(self) -> None:
        try:
            Logger.info(f"Loading translation model '{self.model_name}'...")
            self.pipeline = pipeline("translation", model=self.model_name, device_map="auto")
            Logger.info(f"Translation model '{self.model_name}' loaded successfully.")
        except Exception as e:
            self.load_error = str(e)
            Logger.error(f"Failed to load translation model '{self.model_name}': {e}")
        finally:
            self.loading = False

    def is_ready(self) -> bool:
        return not self.loading and self.pipeline is not None

    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> Dict[str, str]:
        """
        Translate text and return a JSON-serializable result dict.

        Args:
            text: Text to translate
            from_lang: Reserved for future routing (model is multi->en)
            to_lang: Target language (model outputs English)
        """
        current_time = time.time()

        # Drop expired cache entries
        self._cache = {
            k: v for k, v in self._cache.items()
            if current_time - v['timestamp'] < CACHE_TTL_SECONDS
        }

        cache_key = f"{text[:100]}_{from_lang}_{to_lang}"
        if cache_key in self._cache:
            Logger.debug(f"Returning cached translation for: '{text[:50]}...'")
            return {
                "translation": self._cache[cache_key]['translation'],
                "from": from_lang,
                "to": to_lang,
                "cached": True
            }

        if self.loading:
            return {"translation": "[Translation model is still loading... Please wait]", "error": "Model loading"}

        if self.load_error:
            return {"translation": f"[Translation model failed to load: {self.load_error}]", "error": self.load_error}

        try:
            result = self.pipeline(text)
            translation = result[0]['translation_text']

            self._cache[cache_key] = {"translation": translation, "timestamp": current_time}
            Logger.info(f"Translation: '{text[:50]}...' -> '{translation[:50]}...'")
            return {"translation": translation, "from": from_lang, "to": to_lang}
        except Exception as e:
            Logger.error(f"Translation failed: {e}")
            return {"translation": f"[Translation error: {e}]", "error": str(e)}

    def close(self) -> None:
        self._executor.shutdown(wait=True)
