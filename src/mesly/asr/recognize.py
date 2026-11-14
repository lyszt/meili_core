"""
Mandarin speech recognition over captured desktop audio (faster-whisper).
"""

import os

import numpy as np

from ..utils import Logger
from ..utils.inference import inference_lock

MODEL_NAME = "small"


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
                cpu_threads = max(1, os.cpu_count() or 1)
                Logger.info(f"ASR: loading whisper '{MODEL_NAME}' "
                            f"(cpu_threads={cpu_threads}, compute_type=int8, "
                            "first run downloads it)...")
                self.model = WhisperModel(
                    MODEL_NAME, device="cpu", compute_type="int8",
                    cpu_threads=cpu_threads, num_workers=1)
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
            with inference_lock:
                segments, _info = self.model.transcribe(
                    audio, language="zh", vad_filter=False, beam_size=1,
                    best_of=1, temperature=0.0,
                    condition_on_previous_text=False, without_timestamps=True)
            texts = [s.text.strip() for s in segments if s.text.strip()]
            return "".join(texts)
        except Exception as e:
            Logger.error(f"ASR: transcription failed: {e}")
            return ""
