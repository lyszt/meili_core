"""
Mandarin speech recognition over captured desktop audio (faster-whisper).
"""

import numpy as np

from ..utils import Logger

MODEL_SIZE = "small"


class AsrService:
    """Loads the whisper model once and transcribes utterances."""

    def __init__(self):
        self.model = None
        self._load_failed = False

    def _ensure_model(self) -> bool:
        if self._load_failed:
            return False
        if self.model is None:
            try:
                from faster_whisper import WhisperModel
                Logger.info("ASR: loading whisper model "
                            "(the first run downloads it)...")
                self.model = WhisperModel(
                    MODEL_SIZE, device="cpu", compute_type="int8")
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
