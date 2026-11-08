"""
Mandarin speech recognition over captured desktop audio (faster-whisper).
"""

import os

import numpy as np

from ..utils import Logger

# Whisper model size. "medium" hears noticeably better than "small" at
# 3-4x the CPU cost; "large-v3" is not usable on this class of machine.
# Override with the MESLY_ASR_MODEL environment variable.
DEFAULT_MODEL = "small"


class AsrService:
    """Loads the whisper model once and transcribes utterances."""

    def __init__(self, model_name: str = None):
        self.model_name = model_name or os.environ.get(
            "MESLY_ASR_MODEL", DEFAULT_MODEL)
        self.model = None
        self._load_failed = False

    def _ensure_model(self) -> bool:
        if self._load_failed:
            return False
        if self.model is None:
            try:
                from faster_whisper import WhisperModel
                Logger.info(f"ASR: loading whisper '{self.model_name}' "
                            "(the first run downloads it)...")
                self.model = WhisperModel(
                    self.model_name, device="cpu", compute_type="int8")
                Logger.info("ASR: model ready")
            except Exception as e:
                self._load_failed = True
                Logger.error(f"ASR: model load failed: {e}")
                return False
        return True

    def transcribe(self, audio: np.ndarray) -> str:
        """Return the recognized Mandarin text for a float32 utterance."""
        if not self._ensure_model() or audio.size == 0:
            return ""
        try:
            segments, _info = self.model.transcribe(
                audio, language="zh", vad_filter=True, beam_size=1,
                condition_on_previous_text=False)
            texts = [s.text.strip() for s in segments if s.text.strip()]
            return "".join(texts)
        except Exception as e:
            Logger.error(f"ASR: transcription failed: {e}")
            return ""
