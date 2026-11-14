"""Shared lock to serialize CPU-heavy inference (OCR/ASR/translation/TTS)."""

import threading

inference_lock = threading.Lock()
