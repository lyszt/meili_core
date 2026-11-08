"""
ASR worker: captures desktop audio, segments utterances by energy and
emits recognized Mandarin text for the study card.
"""

import time

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from ..utils import Logger
from .capture import MonitorCapture, SAMPLE_RATE
from .recognize import AsrService

# Energy gate below which audio counts as silence
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

    def run(self):
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

    def _on_chunk(self, chunk: np.ndarray):
        """Energy-based utterance segmentation; runs on the worker
        thread (parec blocks in read_loop, so nothing queues behind
        this while we transcribe)."""
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        if rms >= RMS_GATE:
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
            seconds = len(self._buffer) / SAMPLE_RATE
            started = time.perf_counter()
            text = self.service.transcribe(self._buffer)
            Logger.info(
                f"ASR {time.perf_counter() - started:.2f}s "
                f"({seconds:.1f}s audio): '{text[:60]}'")
            if text:
                self.utterance.emit(text)
        self._buffer = np.empty(0, dtype=np.float32)
        self._speech = 0.0
        self._silence = 0.0

    def stop(self):
        if self.capture is not None:
            self.capture.stop()
        self.wait(5000)
