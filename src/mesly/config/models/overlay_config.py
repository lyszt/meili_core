"""
Overlay configuration dataclass
"""

from dataclasses import dataclass


@dataclass
class OverlayConfig:
    """Overlay display configuration"""
    enabled: bool = True
    font_size: int = 14
    background_opacity: float = 0.8
    position: str = "bottom"
    text_color: str = "#FFFFFF"
    background_color: str = "#000000"
