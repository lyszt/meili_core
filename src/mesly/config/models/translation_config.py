"""
Translation configuration dataclass
"""

from dataclasses import dataclass

DEFAULT_MODEL = "facebook/nllb-200-distilled-600M"


@dataclass
class TranslationConfig:
    """Translation service configuration"""
    service: str = "helsinki-nlp"
    model: str = DEFAULT_MODEL
    source_language: str = "zh"
    target_language: str = "en"
    cache_enabled: bool = True
