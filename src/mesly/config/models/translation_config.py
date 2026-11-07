"""
Translation configuration dataclass
"""

from dataclasses import dataclass


@dataclass
class TranslationConfig:
    """Translation service configuration"""
    service: str = "helsinki-nlp"  # Local MarianMT pipeline
    source_language: str = "auto"
    target_language: str = "en"
    cache_enabled: bool = True
