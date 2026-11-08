"""
Translation configuration dataclass
"""

from dataclasses import dataclass

# Default is a dedicated Chinese->English model: smaller and higher quality
# for Mandarin than the multi-language mul-en variant (change if needed).
DEFAULT_MODEL = "Helsinki-NLP/opus-mt-zh-en"


@dataclass
class TranslationConfig:
    """Translation service configuration"""
    service: str = "helsinki-nlp"
    model: str = DEFAULT_MODEL
    source_language: str = "zh"
    target_language: str = "en"
    cache_enabled: bool = True
