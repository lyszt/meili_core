"""
Open-window enumeration and live window capture (X11 via wmctrl/xdotool).
"""

import subprocess
from typing import Callable, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from PIL import Image

from ..utils import Logger
from .screen_capture import ScreenCapture

# wmctrl -lG keeps only visible, reasonably sized windows
MIN_WINDOW_SIZE = 80
# Never stream these (they are ours)
OWN_TITLE_KEYWORDS = ("Mesly",)


def _run(cmd: List[str], timeout: float = 2.0) -> Optional[str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


class WindowLister:
    """Enumerates open windows using wmctrl (preferred) or xdotool."""

    @staticmethod
    def list_windows() -> List[dict]:
        """
        Returns a list of {'id': str, 'title': str, 'box': (left, top, width, height)}.
        Empty list means no window enumeration tool is available (e.g. Wayland).
        """
        windows = WindowLister._list_wmctrl()
        if windows:
            return windows
        return WindowLister._list_xdotool()

    @staticmethod
    def _list_wmctrl() -> List[dict]:
        output = _run(["wmctrl", "-lG"])
        if not output:
            return []

        windows = []
        for line in output.splitlines():
            parts = line.split(None, 7)
            if len(parts) < 8:
                continue
            wid, desktop = parts[0], parts[1]
            if desktop == "-1":
                continue  # Skip docks/desktops
            try:
                x, y, w, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
            except ValueError:
                continue
            title = parts[7].strip()
            if not title or w < MIN_WINDOW_SIZE or h < MIN_WINDOW_SIZE:
                continue
            if any(keyword.lower() in title.lower() for keyword in OWN_TITLE_KEYWORDS):
                continue
            windows.append({"id": wid, "title": title, "box": (x, y, w, h)})
        return windows

    @staticmethod
    def _list_xdotool() -> List[dict]:
        output = _run(["xdotool", "search", "--onlyvisible", "--name", "."])
        if not output:
            return []

        windows = []
        for wid in output.split():
            geometry = _run(["xdotool", "getwindowgeometry", "--shell", wid])
            name = _run(["xdotool", "getwindowname", wid])
            if not geometry or not name:
                continue
            fields = dict(
                line.split("=", 1)
                for line in geometry.splitlines()
                if "=" in line
            )
            try:
                box = (int(fields["X"]), int(fields["Y"]), int(fields["WIDTH"]), int(fields["HEIGHT"]))
            except (KeyError, ValueError):
                continue
            title = name.strip()
            w, h = box[2], box[3]
            if not title or w < MIN_WINDOW_SIZE or h < MIN_WINDOW_SIZE:
                continue
            if any(keyword.lower() in title.lower() for keyword in OWN_TITLE_KEYWORDS):
                continue
            windows.append({"id": wid, "title": title, "box": box})
        return windows


class WindowBoxProvider:
    """
    Returns the current bounding box of a chosen window, re-queried on every
    call so the capture keeps following the window when it moves or resizes.
    Falls back to the last known box if the window cannot be found anymore.
    """

    def __init__(self, window: dict):
        self.window_id = window["id"]
        self._fallback_box = window["box"]

    def __call__(self) -> Optional[tuple]:
        geometry = _run(["xdotool", "getwindowgeometry", "--shell", self.window_id], timeout=1.0)
        if geometry:
            fields = dict(
                line.split("=", 1)
                for line in geometry.splitlines()
                if "=" in line
            )
            try:
                box = (int(fields["X"]), int(fields["Y"]), int(fields["WIDTH"]), int(fields["HEIGHT"]))
                self._fallback_box = box
                return box
            except (KeyError, ValueError):
                pass
        return self._fallback_box


class MonitorBoxProvider:
    """Returns the primary monitor's bounding box."""

    def __init__(self, screen_capture: ScreenCapture):
        self.screen_capture = screen_capture

    def __call__(self) -> Optional[tuple]:
        return self.screen_capture.get_primary_monitor_box()


class WindowCapture(QThread):
    """
    Live capture thread: streams frames of a screen region at a fixed FPS.
    The region is re-resolved every frame through `get_box`, so it can
    follow a moving window.
    """

    frame = pyqtSignal(object)  # PIL Image
    lost = pyqtSignal()         # source box can no longer be resolved

    def __init__(self, get_box: Callable, fps: int = 10):
        super().__init__()
        self.get_box = get_box
        self.fps = max(1, fps)
        self.running = True
        self.screen_capture = ScreenCapture()

    def run(self):
        Logger.info("Live window capture started")
        while self.running:
            box = self.get_box()
            if box is None:
                Logger.warning("Live capture: source window lost")
                self.lost.emit()
                break

            img_array = self.screen_capture.capture_region(box)
            if img_array is None:
                # Region capture failed (e.g. Wayland): try the full chain
                # (MSS -> PyAutoGUI -> Wayland CLI tools), which can still
                # deliver fullscreen frames.
                img_array = self.screen_capture.capture_screen()

            if img_array is not None:
                self.frame.emit(Image.fromarray(img_array))

            self.msleep(int(1000 / self.fps))
        Logger.info("Live window capture stopped")

    def stop(self):
        self.running = False
        self.wait()
