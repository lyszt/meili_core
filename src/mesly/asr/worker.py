"""
ASR worker: captures desktop audio, segments utterances by energy and
emits recognized Mandarin text for the study card.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from ..utils import Logger
from .capture import MonitorCapture, SAMPLE_RATE
from .recognize import AsrService

try:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    _VAD_OPTIONS = VadOptions(min_silence_duration_ms=700, speech_pad_ms=100)
except Exception:
    _VAD_OPTIONS = None

# Fallback energy gate when Silero VAD is unavailable
RMS_GATE = 0.01
# Silence that closes an utterance (seconds)
SILENCE_CLOSE = 0.9
# Minimum speech to bother transcribing (seconds)
MIN_SPEECH = 0.3
# Force-close long utterances (seconds): continuous dialogue never hits
# the silence gate, and 20s monsters drowned the card, so keep the
# whisper context small
MAX_UTTERANCE = 8.0


class AsrWorker(QThread):
    """Listen to the desktop audio and emit per-utterance hanzi."""

    utterance = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = AsrService()
        self.capture = None
        self._executor = None

    def run(self):
        # Transcription runs in its own pool so the capture loop keeps
        # consuming audio while whisper works (otherwise audio drops and
        # a quit mid-transcription hangs teardown)
        self._executor = ThreadPoolExecutor(max_workers=1,
                                            thread_name_prefix="asr-transcribe")
        self._buffer = np.empty(0, dtype=np.float32)
        self._speech = 0.0
        self._silence = 0.0
        self.capture = MonitorCapture(self._on_chunk)
        if not self.capture.start():
            self.status.emit("ASR failed to start (no audio source)")
            return
        self.status.emit("Listening to desktop audio")
        self.capture.read_loop()
        self.capture.stop()
        self._executor.shutdown(wait=False)

    @staticmethod
    def _chunk_is_speech(chunk: np.ndarray) -> bool:
        """Music and effects are not speech: Silero VAD decides, with an
        energy fallback if the model is unavailable."""
        if _VAD_OPTIONS is not None:
            try:
                return bool(get_speech_timestamps(chunk, _VAD_OPTIONS))
            except Exception:
                pass
        return float(np.sqrt(np.mean(chunk * chunk))) >= RMS_GATE

    def _on_chunk(self, chunk: np.ndarray):
        """Utterance segmentation driven by speech detection."""
        if self._chunk_is_speech(chunk):
            self._speech += len(chunk) / SAMPLE_RATE
            self._silence = 0.0
        else:
            self._silence += len(chunk) / SAMPLE_RATE
        self._buffer = np.concatenate((self._buffer, chunk))
        total = len(self._buffer) / SAMPLE_RATE
        done = (self._speech >= MIN_SPEECH
                and (self._silence >= SILENCE_CLOSE
                     or total >= MAX_UTTERANCE))
        if not done:
            return
        if self._speech >= MIN_SPEECH:
            self._executor.submit(self._transcribe, self._buffer.copy())
        self._buffer = np.empty(0, dtype=np.float32)
        self._speech = 0.0
        self._silence = 0.0

    def _transcribe(self, audio: np.ndarray):
        seconds = len(audio) / SAMPLE_RATE
        started = time.perf_counter()
        text = self.service.transcribe(audio)
        Logger.info(
            f"ASR {time.perf_counter() - started:.2f}s "
            f"({seconds:.1f}s audio): '{text[:60]}'")
        if text:
            self.utterance.emit(text)

    def stop(self):
        if self.capture is not None:
            self.capture.stop()
        for _ in range(20):
            if not self.isRunning():
                return
            self.wait(500)
        Logger.warning("ASR: worker did not finish in time")
