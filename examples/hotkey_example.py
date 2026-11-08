"""
Example: PyQt5 window with pynput hotkeys running in parallel
"""

import sys
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt, pyqtSignal, QObject

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mesly.utils import HotkeyManager, Logger
from mesly.capture import ScreenCapture


class Communicator(QObject):
    """Signal communicator for thread-safe GUI updates"""
    hotkey_triggered = pyqtSignal(str)


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mesly - OCR Language Learning Tool")
        self.setGeometry(100, 100, 800, 600)

        # Setup screen capture
        self.screen_capture = ScreenCapture()

        # Setup UI
        self.setup_ui()

        # Setup hotkeys
        self.setup_hotkeys()

        # Signal communicator for thread-safe updates
        self.comm = Communicator()
        self.comm.hotkey_triggered.connect(self.on_hotkey_triggered)

    def setup_ui(self):
        """Setup the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()

        self.status_label = QLabel("Ready. Press Ctrl+Alt+S to capture screenshot")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; padding: 20px;")

        layout.addWidget(self.status_label)
        central_widget.setLayout(layout)

    def setup_hotkeys(self):
        """Setup global hotkeys"""
        self.hotkey_manager = HotkeyManager()

        # Register Ctrl+Alt+S
        self.hotkey_manager.register(
            '<ctrl>+<alt>+s',
            lambda: self.comm.hotkey_triggered.emit("Ctrl+Alt+S")
        )

        # Start listening in background thread
        self.hotkey_manager.start()

    def on_hotkey_triggered(self, hotkey: str):
        """Handle hotkey press (runs in main thread)"""
        Logger.info(f"Hotkey pressed: {hotkey}")

        # Capture screenshot
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"data/screenshots/screenshot_{timestamp}.png"

        # Create directory if it doesn't exist
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # Capture and save
        if self.screen_capture.capture_and_save(filepath):
            self.status_label.setText(f"Screenshot saved!\n\n{filepath}\n\nPress Ctrl+Alt+S to capture again")
        else:
            self.status_label.setText("Failed to capture screenshot\n\nPress Ctrl+Alt+S to try again")

    def closeEvent(self, event):
        """Handle window close event"""
        Logger.info("Closing application...")
        self.hotkey_manager.stop()
        event.accept()


def main():
    """Main application entry point"""
    Logger.info("Starting Mesly application...")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    Logger.info("Application running. Press Ctrl+Alt+S to test hotkey.")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
