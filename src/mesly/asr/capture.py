"""
Desktop audio capture from the PipeWire/Pulse default output monitor.

Uses parec (no portal, no permissions): anything the speakers play is
captured as 16 kHz mono PCM.
"""

import subprocess
from typing import Callable, Optional

import numpy as np

from ..utils import Logger

SAMPLE_RATE = 16000
# 100 ms of s16le mono at 16 kHz
CHUNK_BYTES = 3200


def default_monitor_source() -> Optional[str]:
    """The default sink's monitor source (what the speakers play)."""
    try:
        sink = subprocess.check_output(
            ["pactl", "get-default-sink"], text=True).strip()
        return f"{sink}.monitor"
    except Exception as e:
        Logger.error(f"ASR: cannot query default sink: {e}")
        return None


class MonitorCapture:
    """Streams 16 kHz mono float32 chunks from the desktop monitor."""

    def __init__(self, on_chunk: Callable[[np.ndarray], None],
                 source: Optional[str] = None):
        self.on_chunk = on_chunk
        self.source = source or default_monitor_source()
        self._process = None
        self._closed = False

    def start(self) -> bool:
        if not self.source:
            Logger.error("ASR: no monitor source to capture")
            return False
        cmd = ["parec", "-d", self.source, "--file-format=raw",
               "--format=s16le", "--rate", str(SAMPLE_RATE),
               "--channels", "1"]
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            Logger.error(f"ASR: cannot start parec: {e}")
            return False
        Logger.info(f"ASR: capturing from {self.source}")
        return True

    def read_loop(self):
        """Blocking read loop; run it in the worker thread."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        while not self._closed:
            raw = proc.stdout.read(CHUNK_BYTES)
            if not raw:
                # Empty read: parec died - surface its error instead of
                # dying silently
                if not self._closed and proc.stderr is not None:
                    error = proc.stderr.read().decode(errors="replace").strip()
                    if error:
                        Logger.error(f"ASR: parec exited: {error}")
                break
            samples = np.frombuffer(raw, dtype=np.int16)
            self.on_chunk(samples.astype(np.float32) / 32768.0)

    def stop(self):
        self._closed = True
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(2)
            except Exception:
                self._process.kill()
            self._process = None
