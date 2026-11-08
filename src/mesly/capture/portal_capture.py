"""
Wayland-compatible live capture via the xdg-desktop-portal ScreenCast API.

PortalCapture spawns the dedicated portal_worker process: a standalone
environment (own GLib default context, no Qt) is the only way this reliably
binds the picked window on Plasma - binding from inside the Qt process
lands on the session manager's default video source (the webcam).

Frames arrive as JPEG over the worker's stdout (see portal_worker.py for
the protocol).
"""

import io
import os
import select
import struct
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal

from ..utils import Logger

WORKER_PATH = Path(__file__).resolve().parent / "portal_worker.py"

# How long to wait for the worker's READY line (picker interaction included)
STARTUP_TIMEOUT_SECONDS = 150


def portal_available() -> bool:
    """Whether the portal capture stack (PyGObject + GStreamer) is importable."""
    try:
        import gi  # noqa: F401
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401
        return True
    except Exception:
        return False


class PortalCapture(QThread):
    """
    Live capture through the desktop portal, executed by portal_worker.
    The system shows a native window/screen picker; frames stream over a pipe.
    """

    frame = pyqtSignal(object)  # PIL Image
    error = pyqtSignal(str)
    status = pyqtSignal(str)    # progress updates for the UI

    def __init__(self):
        super().__init__()
        self.running = True
        self._process = None
        self._verified = False
        self._first_w = 0
        self._first_h = 0

    def stop(self):
        self.running = False

    def run(self):
        self.status.emit("Waiting for you to pick a source in the system dialog...")
        try:
            self._process = subprocess.Popen(
                [sys.executable, str(WORKER_PATH)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as e:
            self.error.emit(f"Could not start the portal worker: {e}")
            return

        # Drain stderr in the background so nobody deadlocks
        import threading

        def _drain_stderr():
            try:
                for raw_line in iter(self._process.stderr.readline, b""):
                    Logger.info(f"Portal worker: {raw_line.decode(errors='replace').rstrip()}")
            except Exception:
                pass

        threading.Thread(target=_drain_stderr, daemon=True).start()

        frames_total = 0
        start = time.monotonic()
        try:
            frames_total = self._read_worker_output(start)
        except Exception as e:
            Logger.error(f"Portal worker reader failed: {e}")
            self.error.emit(f"Portal stream failed: {e}")
        finally:
            self._terminate_worker()

        Logger.info(f"Portal capture ended ({frames_total} frames)")

    def _read_worker_output(self, start: float) -> int:
        """Parse the worker protocol; returns the number of frames emitted."""
        proc = self._process
        buffer = b""
        frames = 0

        while self.running:
            if proc.poll() is not None:
                break

            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if not ready:
                if frames == 0 and time.monotonic() - start > STARTUP_TIMEOUT_SECONDS:
                    self.error.emit(
                        "Portal worker timed out waiting for a source selection"
                    )
                    break
                continue

            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            buffer += chunk

            # Extract protocol messages from the buffer
            while buffer:
                if buffer.startswith(b"MESLYF"):
                    if len(buffer) < 10:
                        break
                    (length,) = struct.unpack(">I", buffer[6:10])
                    if len(buffer) < 10 + length:
                        break
                    jpeg = buffer[10:10 + length]
                    buffer = buffer[10 + length:]
                    image = Image.open(io.BytesIO(jpeg))
                    image.load()
                    frames += 1
                    if frames == 1:
                        self._first_w, self._first_h = image.size
                        self.status.emit("Live share streaming")
                    self.frame.emit(image)
                elif buffer.startswith(b"MESLY "):
                    line_end = buffer.find(b"\n")
                    if line_end == -1:
                        # drop overly long garbage
                        if len(buffer) > 4096:
                            buffer = b""
                        break
                    line = buffer[:line_end].decode(errors="replace")
                    buffer = buffer[line_end + 1:]
                    self._handle_worker_line(line)
                else:
                    # Unknown bytes: drop until the next protocol marker
                    index = buffer.find(b"MESLY")
                    buffer = buffer[index:] if index >= 0 else b""
        return frames

    def _handle_worker_line(self, line: str):
        body = line[len("MESLY "):]
        if body.startswith("ERR"):
            message = body[len("ERR"):].strip()
            Logger.error(f"Portal worker: {message}")
            self.error.emit(message)
        elif body.startswith("READY"):
            Logger.info(f"Portal worker ready: {body}")
        elif body.startswith("PICKER"):
            self.status.emit("Pick a source in the system dialog...")
        else:
            Logger.debug(f"Portal worker: {line}")

    def _terminate_worker(self):
        if self._process is None:
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            try:
                self._process.kill()
                self._process.wait(timeout=2)
            except Exception:
                pass
        finally:
            self._process = None
