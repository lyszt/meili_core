"""
System specs detection for feature gating (local LLM, NeuTTS, etc.)
"""

import os
from pathlib import Path
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

try:
    import torch
except ImportError:
    torch = None

from .gpuconfig import GPUConfig
from ..utils import Logger


class SystemSpecs:
    """Detects system hardware and provides feature capability flags."""

    def __init__(self, neutts_vendor_path: Optional[Path] = None):
        """
        Initialize and detect system specs.

        Args:
            neutts_vendor_path: Path to vendor/neutts. If None, uses ROOT/vendor/neutts.
        """
        self.gpu_config = GPUConfig()
        self.cpu_cores: int = os.cpu_count() or 0
        self.ram_total_gb: float = 0.0
        self.ram_available_gb: float = 0.0
        self.swap_used_gb: float = 0.0
        self.swap_total_gb: float = 0.0
        self.vram_gb: Optional[float] = None
        self._neutts_vendor_path = neutts_vendor_path
        self._detect_ram()
        self._detect_swap()
        self._detect_vram()

    def _detect_ram(self) -> None:
        """Detect system RAM using psutil.
        Uses the lesser of available and free+2GB as a conservative estimate:
        'available' can be optimistic (reclaimable cache); under load, model
        loading can trigger OOM. Prefer a stricter estimate when free is low.
        """
        if psutil is None:
            Logger.warning("psutil not installed; assuming specs sufficient for feature gating")
            self.ram_total_gb = 16.0
            self.ram_available_gb = 8.0
            return

        try:
            vmem = psutil.virtual_memory()
            self.ram_total_gb = vmem.total / (1024 ** 3)
            available_gb = vmem.available / (1024 ** 3)
            free_gb = vmem.free / (1024 ** 3)
            # Conservative: if free is much lower than available, we're under pressure
            self.ram_available_gb = min(available_gb, free_gb + 2.0)
        except Exception as e:
            Logger.warning(f"Failed to detect RAM: {e}; assuming specs sufficient")
            self.ram_total_gb = 16.0
            self.ram_available_gb = 8.0

    def _detect_swap(self) -> None:
        """Detect swap usage. High swap = system under memory pressure."""
        if psutil is None:
            self.swap_used_gb = 0.0
            self.swap_total_gb = 0.0
            return
        try:
            swap = psutil.swap_memory()
            self.swap_used_gb = swap.used / (1024 ** 3)
            self.swap_total_gb = swap.total / (1024 ** 3)
        except Exception:
            self.swap_used_gb = 0.0
            self.swap_total_gb = 0.0

    def _detect_vram(self) -> None:
        """Detect GPU VRAM when CUDA is available."""
        self.vram_gb = None
        if torch is not None and torch.cuda.is_available():
            try:
                props = torch.cuda.get_device_properties(0)
                self.vram_gb = props.total_memory / (1024 ** 3)
            except Exception:
                pass

    def supports_neutts(
        self,
        min_ram_gb: float = 8.0,
        max_swap_used_gb: float = 4.0,
    ) -> bool:
        """Check if system has enough resources and vendor path for NeuTTS.
        Disables when swap is heavily used (system under pressure - OOM risk).
        """
        if self.ram_available_gb < min_ram_gb:
            return False
        if self.swap_used_gb > max_swap_used_gb:
            return False
        path = self._get_neutts_vendor_path()
        return path is not None and path.exists()

    def _get_neutts_vendor_path(self) -> Optional[Path]:
        """Get path to vendor/neutts."""
        if self._neutts_vendor_path is not None:
            return self._neutts_vendor_path
        try:
            root = Path(__file__).resolve().parents[3]
            return root / "vendor" / "neutts"
        except Exception:
            return None

    @property
    def gpu_available(self) -> bool:
        """Whether GPU is available and compatible."""
        return self.gpu_config.is_gpu_available()

    def get_specs_summary(self) -> dict:
        """Get a dict summary of detected specs for logging/API."""
        summary = {
            "cpu_cores": self.cpu_cores,
            "ram_total_gb": round(self.ram_total_gb, 2),
            "ram_available_gb": round(self.ram_available_gb, 2),
            "swap_used_gb": round(self.swap_used_gb, 2),
            "swap_total_gb": round(self.swap_total_gb, 2),
            "gpu_available": self.gpu_available,
            "gpu_name": self.gpu_config.device_name,
        }
        if self.vram_gb is not None:
            summary["vram_gb"] = round(self.vram_gb, 2)
        neutts_path = self._get_neutts_vendor_path()
        summary["neutts_vendor_present"] = neutts_path is not None and neutts_path.exists()
        return summary
