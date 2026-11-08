"""
Screen capture functionality - Fullscreen only
Simplified version that captures the entire screen.
"""
import numpy as np
import subprocess
import os
from PIL import Image
from typing import Optional
from ..utils import Logger

# Check for libraries
try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False


class ScreenCapture:
    def __init__(self):
        self.sct = None
        if HAS_MSS:
            try:
                self.sct = mss.mss()
            except Exception as e:
                Logger.warning(f"Failed to initialize mss: {e}")
                self.sct = None

    def capture_screen(self) -> Optional[np.ndarray]:
        """
        Captures the entire screen.
        Universal capture chain: MSS -> PyAutoGUI -> Native Wayland CLI
        """
        if self.sct:
            try:
                monitor = self.sct.monitors[1]  # Primary monitor
                sct_img = self.sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                return np.array(img)
            except Exception as e:
                Logger.debug(f"MSS capture failed: {e}")

        if HAS_PYAUTOGUI:
            try:
                screenshot = pyautogui.screenshot()
                return np.array(screenshot)
            except Exception as e:
                Logger.debug(f"PyAutoGUI capture failed: {e}")

        return self._capture_wayland_cli()

    def _capture_wayland_cli(self) -> Optional[np.ndarray]:
        """
        Detects the Desktop Environment and uses the native CLI tool.
        Captures fullscreen only.
        """
        def cmd_exists(cmd: str) -> bool:
            """Check if a command exists in PATH"""
            try:
                result = subprocess.run(
                    ["which", cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
                return result.returncode == 0
            except Exception:
                return False

        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        temp_path = "/tmp/mesly_fullscreen_capture.png"

        # Check which tools are available once
        has_spectacle = cmd_exists("spectacle")
        has_grim = cmd_exists("grim")
        has_gnome = cmd_exists("gnome-screenshot")

        # Define potential commands based on DE and what's actually installed
        potential_cmds = []

        if "KDE" in desktop and has_spectacle:
            potential_cmds.append(["spectacle", "-b", "-n", "-o", temp_path])
        elif "GNOME" in desktop and has_gnome:
            potential_cmds.append(["gnome-screenshot", "-f", temp_path])
        elif ("SWAY" in desktop or "HYPRLAND" in desktop) and has_grim:
            potential_cmds.append(["grim", temp_path])

        # Universal fallbacks (try in order of preference, but skip gnome-screenshot if not on GNOME)
        if not potential_cmds:
            if has_spectacle:
                potential_cmds.append(["spectacle", "-b", "-n", "-o", temp_path])
            if has_grim:
                potential_cmds.append(["grim", temp_path])
            # Only use gnome-screenshot as fallback if actually running GNOME
            if has_gnome and "GNOME" in desktop:
                potential_cmds.append(["gnome-screenshot", "-f", temp_path])

        if not potential_cmds:
            Logger.error("No screenshot tool found (spectacle, grim, gnome-screenshot)")
            return None

        for cmd in potential_cmds:
            try:
                # Cleanup old file
                if os.path.exists(temp_path):
                    os.remove(temp_path)

                # Suppress GTK/GNOME warnings by setting environment
                env = os.environ.copy()
                env['G_MESSAGES_DEBUG'] = ''

                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env
                )

                if os.path.exists(temp_path):
                    with Image.open(temp_path) as img:
                        img = img.convert("RGB")
                        img_array = np.array(img)

                    # Cleanup
                    os.remove(temp_path)
                    Logger.debug(f"Captured with {cmd[0]}: {img_array.shape}")
                    return img_array

            except subprocess.CalledProcessError:
                Logger.debug(f"Screenshot tool '{cmd[0]}' failed, trying next...")
                continue
            except Exception as e:
                Logger.debug(f"Capture error with {cmd[0]}: {e}")
                continue

        Logger.error("All screenshot tools failed")
        return None

    def capture_region(self, box) -> Optional[np.ndarray]:
        """
        Captures an arbitrary screen region (absolute screen coordinates)
        and returns the already-cropped RGB array.

        Chain: MSS -> PyAutoGUI -> full capture cropped to the region.

        Args:
            box: (left, top, width, height) in screen coordinates

        Returns:
            Cropped RGB numpy array, or None on failure
        """
        left, top, width, height = box
        if width <= 0 or height <= 0:
            return None

        if self.sct:
            try:
                region = {"left": left, "top": top, "width": width, "height": height}
                sct_img = self.sct.grab(region)
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                return np.array(img)
            except Exception as e:
                Logger.debug(f"MSS region capture failed: {e}")

        if HAS_PYAUTOGUI:
            try:
                screenshot = pyautogui.screenshot(region=(left, top, width, height))
                return np.array(screenshot)
            except Exception as e:
                Logger.debug(f"PyAutoGUI region capture failed: {e}")

        # Full-screen capture cropped to the region (Spectacle on KDE
        # Wayland has no non-interactive rectangle mode)
        full = self.capture_screen()
        if full is None:
            return None
        frame_h, frame_w = full.shape[:2]
        x = max(0, min(left, frame_w - 1))
        y = max(0, min(top, frame_h - 1))
        crop_w = min(width, frame_w - x)
        crop_h = min(height, frame_h - y)
        if crop_w <= 0 or crop_h <= 0:
            return None
        return np.ascontiguousarray(full[y:y + crop_h, x:x + crop_w])

    def get_primary_monitor_box(self) -> Optional[tuple]:
        """Bounding box (left, top, width, height) of the primary monitor, if known."""
        if self.sct:
            try:
                monitor = self.sct.monitors[1]
                return (monitor["left"], monitor["top"], monitor["width"], monitor["height"])
            except Exception as e:
                Logger.debug(f"Failed to read monitor info: {e}")
        return None

    def capture_and_save(self, filepath: str) -> bool:
        """Capture fullscreen and save to file"""
        img_array = self.capture_screen()
        if img_array is not None:
            Image.fromarray(img_array).save(filepath)
            Logger.info(f"Screenshot saved to {filepath}")
            return True
        return False

    def get_monitor_info(self):
        """Get monitor information (if MSS is available)"""
        if self.sct:
            return self.sct.monitors
        return []
