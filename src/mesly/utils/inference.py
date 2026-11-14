"""
Shared gate for CPU-heavy inference so OCR, ASR and translation do not
run at the same time and contend for resources.
"""

import threading

inference_lock = threading.Lock()
