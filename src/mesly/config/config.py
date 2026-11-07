"""
Configuration management for Mesly
"""

import yaml
from pathlib import Path
from typing import Dict

from .models import (
    OCRConfig,
    TranslationConfig,
    CaptureConfig,
    CaptureRegion,
    OverlayConfig,
    PerformanceConfig
)
from ..utils import Logger


class ConfigTemplate:
    """Main configuration template"""

    _instances: Dict[str, 'ConfigTemplate'] = {}

    def __init__(self, filepath: str = "config/config.yaml"):
        """
        Initialize configuration, loading from file or creating default

        Args:
            filepath: Path to config file (default: config/config.yaml)
        """
        self.filepath = Path(filepath)

        # Initialize with defaults
        self.ocr = OCRConfig()
        self.translation = TranslationConfig()
        self.capture = CaptureConfig()
        self.overlay = OverlayConfig()
        self.performance = PerformanceConfig()

        # Load from file if exists, otherwise save defaults
        if self.filepath.exists():
            Logger.info(f"Loading configuration from {self.filepath}")
            self._load()
            Logger.info(f"Configuration loaded successfully")
        else:
            Logger.warning(f"Configuration file not found at {self.filepath}")
            Logger.info(f"Creating default configuration...")
            self.save()
            Logger.info(f"Default configuration saved to {self.filepath}")

    def _load(self) -> None:
        """Load configuration from file"""
        with open(self.filepath, 'r') as f:
            data = yaml.safe_load(f)

        self.ocr = OCRConfig(**data.get("ocr", {}))
        self.translation = TranslationConfig(**data.get("translation", {}))
        self.capture = CaptureConfig(
            fps=data.get("capture", {}).get("fps", 1),
            region=CaptureRegion(**data.get("capture", {}).get("region", {}))
        )
        self.overlay = OverlayConfig(**data.get("overlay", {}))
        perf_data = data.get("performance") or {}
        self.performance = PerformanceConfig(
            use_gpu=perf_data.get("use_gpu", False),
            max_threads=perf_data.get("max_threads", 4),
            min_ram_neutts_gb=perf_data.get("min_ram_neutts_gb", 8.0),
            max_swap_used_gb=perf_data.get("max_swap_used_gb", 6.0),
            neutts_enabled=perf_data.get("neutts_enabled", False),
        )

    def save(self) -> None:
        """Save configuration to file"""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        config_dict = {
            "ocr": self.ocr.__dict__,
            "translation": self.translation.__dict__,
            "capture": {
                "fps": self.capture.fps,
                "region": self.capture.region.__dict__
            },
            "overlay": self.overlay.__dict__,
            "performance": self.performance.__dict__
        }

        with open(self.filepath, 'w') as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
        Logger.info(f"Configuration saved to {self.filepath}")

    def to_yaml(self) -> str:
        """Convert config to YAML string"""
        config_dict = {
            "ocr": self.ocr.__dict__,
            "translation": self.translation.__dict__,
            "capture": {
                "fps": self.capture.fps,
                "region": self.capture.region.__dict__
            },
            "overlay": self.overlay.__dict__,
            "performance": self.performance.__dict__
        }
        return yaml.dump(config_dict, default_flow_style=False, sort_keys=False)

    @classmethod
    def get_config(cls, filepath: str = "config/config.yaml") -> 'ConfigTemplate':
        """
        Get configuration instance - automatically loads or creates index file
        Uses singleton pattern to ensure index is only loaded once per filepath

        Args:
            filepath: Path to config file (default: config/config.yaml)

        Returns:
            Ready-to-use ConfigTemplate instance
        """
        # Normalize the filepath
        normalized_path = str(Path(filepath).resolve())

        # Return existing instance if already loaded
        if normalized_path in cls._instances:
            Logger.debug(f"Using cached configuration from {filepath}")
            return cls._instances[normalized_path]

        # Create new instance and cache it
        instance = cls(filepath)
        cls._instances[normalized_path] = instance
        return instance
