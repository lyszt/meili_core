"""
Global hotkey listener using pynput
"""

import threading
from typing import Callable, Optional, Dict
from pynput import keyboard
from .logger import Logger


class HotkeyManager:
    """Manages global hotkeys using pynput in a background thread"""

    def __init__(self):
        self._listener: Optional[keyboard.Listener] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._hotkeys: Dict[str, Callable] = {}
        self._running = False

    def register(self, hotkey: str, callback: Callable) -> None:
        """
        Register a hotkey with callback

        Args:
            hotkey: Hotkey combination (e.g., '<ctrl>+<shift>+t')
            callback: Function to call when hotkey is pressed
        """
        self._hotkeys[hotkey] = callback
        Logger.info(f"Registered hotkey: {hotkey}")

    def start(self) -> None:
        """Start listening for hotkeys in background thread"""
        if self._running:
            Logger.warning("Hotkey listener already running")
            return

        Logger.info("Starting hotkey listener...")

        self._listener = keyboard.GlobalHotKeys(self._hotkeys)

        self._listener_thread = threading.Thread(
            target=self._listener.start,
            daemon=True,
            name="HotkeyListener"
        )
        self._listener_thread.start()
        self._running = True

        Logger.info(f"Hotkey listener started with {len(self._hotkeys)} hotkeys")

    def stop(self) -> None:
        """Stop listening for hotkeys"""
        if not self._running:
            return

        Logger.info("Stopping hotkey listener...")

        if self._listener:
            self._listener.stop()
            self._listener = None

        self._running = False
        Logger.info("Hotkey listener stopped")

    def is_running(self) -> bool:
        """Check if listener is running"""
        return self._running

    def clear_hotkeys(self) -> None:
        """Clear all registered hotkeys"""
        self._hotkeys.clear()
        Logger.info("Cleared all hotkeys")
