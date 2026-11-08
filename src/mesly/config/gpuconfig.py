import torch
import warnings
import os
from ..utils import Logger


class GPUConfig:
    def __init__(self):
        """Initialize GPU configuration with automatic detection and fallback"""
        self.device = None
        self.device_name = None
        self.cuda_available = torch.cuda.is_available()
        self.gpu_compatible = False

        # Suppress PyTorch CUDA warnings during detection
        warnings.filterwarnings('ignore', category=UserWarning, module='torch')
        warnings.filterwarnings('ignore', category=UserWarning, module='torch.cuda')

        self._detect_and_configure()

    def _detect_and_configure(self):
        """Detect GPU and configure device"""
        if not self.cuda_available:
            self._set_cpu("CUDA not available")
            return

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                gpu_name = torch.cuda.get_device_name(0)
                gpu_capability = torch.cuda.get_device_capability(0)

            # Check CUDA compute capability
            # PyTorch current version supports sm_70+ (CUDA capability 7.0+)
            min_capability = (7, 0)

            if gpu_capability < min_capability:
                Logger.warning(
                    f"GPU '{gpu_name}' has CUDA capability {gpu_capability[0]}.{gpu_capability[1]}, "
                    f"but PyTorch requires minimum {min_capability[0]}.{min_capability[1]}"
                )
                # Force CPU mode only for incompatible GPU
                os.environ['CUDA_VISIBLE_DEVICES'] = ''
                self._set_cpu(
                    f"GPU incompatible (CUDA capability "
                    f"{gpu_capability[0]}.{gpu_capability[1]} < "
                    f"{min_capability[0]}.{min_capability[1]})")
            else:
                # GPU is compatible - use it
                self.device = torch.device("cuda:0")
                self.device_name = gpu_name
                self.gpu_compatible = True
                Logger.info(f"✅ Using GPU: {gpu_name} (CUDA {gpu_capability[0]}.{gpu_capability[1]})")

        except Exception as e:
            Logger.error(f"Error detecting GPU: {e}")
            self._set_cpu("GPU detection failed")

    def _set_cpu(self, reason: str):
        """Set device to CPU with reason"""
        self.device = torch.device("cpu")
        self.device_name = "CPU"
        self.gpu_compatible = False
        Logger.info(f"⚙️  Using CPU for PyTorch operations ({reason})")

    def get_device(self):
        """Get the configured torch device"""
        return self.device

    def is_gpu_available(self) -> bool:
        """Check if GPU is available and compatible"""
        return self.gpu_compatible

    def get_device_info(self) -> dict:
        """Get detailed device information"""
        info = {
            "device": str(self.device),
            "device_name": self.device_name,
            "cuda_available": self.cuda_available,
            "gpu_compatible": self.gpu_compatible
        }

        if self.cuda_available:
            try:
                capability = torch.cuda.get_device_capability(0)
                info["cuda_capability"] = f"{capability[0]}.{capability[1]}"
                info["gpu_name"] = torch.cuda.get_device_name(0)
            except Exception:
                pass

        return info
