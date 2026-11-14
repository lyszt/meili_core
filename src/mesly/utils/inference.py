"""Shared lock to serialize CPU-heavy OCR and ASR inference."""

import threading

inference_lock = threading.Lock()
