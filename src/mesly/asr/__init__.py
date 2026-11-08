"""
ASR module: capture desktop audio, recognize Mandarin speech.
"""

from .capture import MonitorCapture, default_monitor_source
from .recognize import AsrService
from .worker import AsrWorker

__all__ = ["MonitorCapture", "default_monitor_source", "AsrService",
           "AsrWorker"]
