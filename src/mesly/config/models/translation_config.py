"""
Translation configuration dataclass
"""

from dataclasses import dataclass

# Default translation model. NLLB gives better zh->en quality for dialogue
# than MarianMT opus-mt, at the cost of a larger download and more compute.
DEFAULT_MODEL = "facebook/nllb-200-distilled-600M"


@dataclass
class TranslationConfig:
    """Translation service configuration"""
    service: str = "helsinki-nlp"
    model: str = DEFAULT_MODEL
    source_language: str = "zh"
    target_language: str = "en"
    cache_enabled: bool = True
