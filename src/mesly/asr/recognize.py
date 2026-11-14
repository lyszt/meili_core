"""
Mandarin speech recognition over captured desktop audio (faster-whisper).
"""

import os

import numpy as np

from ..utils import Logger
from ..utils.inference import asr_lock

MODEL_NAME = "small"


class AsrService:
    """Loads the whisper model once and transcribes utterances."""

    def __init__(self):
        self.model = None
        self._load_failed = False

    def _select_device(self):
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda", ["float16", "int8_float16", "float32", "int8"]
        except Exception:
            pass
        return "cpu", ["int8"]

    def _ensure_model(self) -> bool:
        if self._load_failed:
            return False
        if self.model is None:
            try:
                from faster_whisper import WhisperModel
            except Exception as e:
                self._load_failed = True
                Logger.error(f"ASR: model load failed: {e}")
                return False
            cpu_threads = max(1, os.cpu_count() or 1)
            device, compute_types = self._select_device()
            last_error = None
            for compute_type in compute_types:
                try:
                    Logger.info(f"ASR: loading whisper '{MODEL_NAME}' "
                                f"(device={device}, compute_type={compute_type}, "
                                f"cpu_threads={cpu_threads})...")
                    kwargs = {"num_workers": 1}
                    if device == "cpu":
                        kwargs["cpu_threads"] = cpu_threads
                    self.model = WhisperModel(
                        MODEL_NAME, device=device, compute_type=compute_type, **kwargs)
                    Logger.info("ASR: model ready")
                    return True
                except Exception as e:
                    last_error = e
                    self.model = None
            self._load_failed = True
            Logger.error(f"ASR: model load failed: {last_error}")
            return False
        return True

    def transcribe(self, audio: np.ndarray) -> str:
        """Return the recognized Mandarin text for a float32 utterance."""
        if not self._ensure_model() or audio.size == 0:
            return ""
        acquired = asr_lock.acquire(blocking=False)
        if not acquired:
            Logger.info("ASR: skipped (busy)")
            return ""
        try:
            segments, _info = self.model.transcribe(
                audio, language="zh", vad_filter=False, beam_size=1,
                best_of=1, temperature=0.0,
                condition_on_previous_text=False, without_timestamps=True)
            texts = [s.text.strip() for s in segments if s.text.strip()]
            return "".join(texts)
        except Exception as e:
            Logger.error(f"ASR: transcription failed: {e}")
            return ""
        finally:
            asr_lock.release()
