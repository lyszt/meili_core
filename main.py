#!/usr/bin/env python3
"""
Mesly - OCR-based language learning tool for gaming

Main entry point for the application.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.mesly import __version__
from src.mesly.app import MeslyApp


def main():
    """Main application entry point"""
    print(f"Mesly v{__version__}")
    print("OCR Language Learning Tool")


if __name__ == "__main__":
    mesly_app = MeslyApp()
