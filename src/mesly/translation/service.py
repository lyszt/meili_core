"""
Translation service using local Helsinki-NLP (MarianMT) models.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

import torch
from torch import nn
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

from ..utils import Logger

DEFAULT_MODEL = "Helsinki-NLP/opus-mt-zh-en"  # dedicated zh->en model
CACHE_TTL_SECONDS = 10
# MarianMT's positional encoding limit
MAX_MODEL_TOKENS = 512
# Cap on generated tokens: subtitles are short, and an uncapped generate
# can burn whole seconds on the CPU. Scale with the input, never below 16.
MAX_NEW_TOKENS = 64


class TranslationService:
    """Loads the local MarianMT model and translates text to English."""

    def __init__(self, model_name: str = DEFAULT_MODEL, config=None):
        self.model_name = model_name
        self.config = config
        self.tokenizer = None
        self.model = None
        self.loading = True
        self.load_error: Optional[str] = None
        self._cache: Dict[str, Dict] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="translation")
        self._executor.submit(self._load_model)

    def _load_model(self) -> None:
        try:
            Logger.info(f"Loading translation model '{self.model_name}'...")
            # transformers >= 5 removed the "translation" pipeline task, so
            # load the MarianMT tokenizer/model directly (works on v4 and v5).
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)

            # GPU only when explicitly configured AND actually usable. On
            # unsupported cards (e.g. compute capability < 7.0) device_map
            # schemes either crash with mixed-device errors or run broken
            # kernels, so the default is plain CPU.
            using_gpu = False
            if (self.config is not None
                    and getattr(self.config.performance, "use_gpu", False)):
                if torch.cuda.is_available():
                    Logger.info("Translation: moving model to CUDA")
                    self.model.to("cuda")
                    using_gpu = True
                else:
                    Logger.warning("Translation: use_gpu set but CUDA unavailable; staying on CPU")

            if not using_gpu:
                # Int8 dynamic quantization: roughly 2-3x faster MarianMT
                # inference on CPU with negligible quality change
                try:
                    self.model = torch.quantization.quantize_dynamic(
                        self.model, {nn.Linear}, dtype=torch.qint8)
                    Logger.info("Translation: dynamic int8 quantization applied")
                except Exception as e:
                    Logger.warning(f"Translation: quantization skipped ({e})")

            self.model.eval()
            Logger.info(f"Translation model '{self.model_name}' loaded successfully.")
        except Exception as e:
            self.load_error = str(e)
            Logger.error(f"Failed to load translation model '{self.model_name}': {e}")
        finally:
            self.loading = False

    def is_ready(self) -> bool:
        return not self.loading and self.model is not None

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
            t0 = time.perf_counter()
            translation = self._translate_chunks(text)
            elapsed = time.perf_counter() - t0
            self._cache[cache_key] = {"translation": translation, "timestamp": current_time}
            Logger.info(f"Translation ({elapsed:.2f}s): "
                        f"'{text[:50]}...' -> '{translation[:50]}...'")
            return {"translation": translation, "from": from_lang, "to": to_lang}
        except Exception as e:
            Logger.error(f"Translation failed: {e}")
            return {"translation": f"[Translation error: {e}]", "error": str(e)}

    def _translate_chunks(self, text: str) -> str:
        """
        Translate text longer than the model's token limit by splitting on
        line/sentence boundaries first, then hard-splitting any remaining
        over-long chunk.
        """
        tokens = self.tokenizer.encode(text, add_special_tokens=False)
        if len(tokens) <= MAX_MODEL_TOKENS:
            return self._generate(text)

        chunks = self._split_chunks(text)
        return " ".join(self._generate(chunk) for chunk in chunks)

    def _split_chunks(self, text: str) -> list:
        """Split text into chunks that each fit inside the model's token limit."""
        # Prefer natural boundaries: paragraphs, then lines, then sentences
        pieces = []
        for para in text.split("\n"):
            if not para.strip():
                continue
            if len(self.tokenizer.encode(para, add_special_tokens=False)) <= MAX_MODEL_TOKENS:
                pieces.append(para)
                continue
            for part in self._split_hard(para):
                pieces.append(part)

        chunks = []
        current = ""
        for piece in pieces:
            candidate = f"{current} {piece}".strip() if current else piece
            if len(self.tokenizer.encode(candidate, add_special_tokens=False)) <= MAX_MODEL_TOKENS:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = piece
        if current:
            chunks.append(current)
        return chunks

    def _split_hard(self, text: str) -> list:
        """Sentence-first split; falls back to token-window split for monsters."""
        sentences = [
            s for s in text.replace("。", ".\n")
            .replace("！", "!\n").replace("？", "?\n")
            .split(".") if s.strip()]

        pieces = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            pieces.append(sentence)

        result = []
        current = ""
        for piece in pieces:
            candidate = f"{current}. {piece}".strip() if current else piece
            if len(self.tokenizer.encode(candidate, add_special_tokens=False)) <= MAX_MODEL_TOKENS:
                current = candidate
            else:
                if current:
                    result.append(current)
                # A single sentence over the limit gets hard-split by tokens
                if len(self.tokenizer.encode(piece, add_special_tokens=False)) > MAX_MODEL_TOKENS:
                    result.extend(self._split_tokens(piece))
                    current = ""
                else:
                    current = piece
        if current:
            result.append(current)
        return result

    def _split_tokens(self, text: str) -> list:
        """Split an over-long sentence into chunks of at most MAX_MODEL_TOKENS."""
        ids = self.tokenizer.encode(text, add_special_tokens=False)
        chunks = []
        for i in range(0, len(ids), MAX_MODEL_TOKENS):
            chunk_ids = ids[i:i + MAX_MODEL_TOKENS]
            chunks.append(self.tokenizer.decode(chunk_ids, skip_special_tokens=True))
        return chunks

    def _generate(self, text: str) -> str:
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=MAX_MODEL_TOKENS)
        # Guard against mixed devices (model on GPU, inputs on CPU)
        device = self.model.device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[1]
        output = self.model.generate(
            **inputs,
            max_new_tokens=max(16, min(MAX_NEW_TOKENS, 2 * input_len)))
        return self.tokenizer.decode(output[0], skip_special_tokens=True).strip()

    def close(self) -> None:
        self._executor.shutdown(wait=True)
