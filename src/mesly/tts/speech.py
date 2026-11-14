"""
Text-to-speech synthesis: local NeuTTS with gTTS fallback.
"""

import io
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
from gtts import gTTS
from scipy.io.wavfile import write

from ..config import ConfigTemplate, SystemSpecs
from ..utils import Logger

ROOT = Path(__file__).resolve().parents[3]

# NeuTTS synthesizes 24kHz PCM
NEUTTS_SAMPLE_RATE = 24000
NEUTTS_REF_TEXT = "The quick brown fox jumps over the lazy dog."


class SpeechSynthesizer:
    """Synthesizes text to audio bytes. Prefers local NeuTTS, falls back to gTTS."""

    def __init__(self, config: ConfigTemplate, specs: Optional[SystemSpecs] = None):
        self.config = config
        self.specs = specs if specs is not None else SystemSpecs()
        self._ref_codes = None
        self.engine = self._init_neutts()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")

    def _init_neutts(self):
        """Conditionally initialize NeuTTS based on config and system resources."""
        if not getattr(self.config.performance, "neutts_enabled", False):
            Logger.debug("Speech: NeuTTS disabled in config")
            return None

        min_ram = getattr(self.config.performance, "min_ram_neutts_gb", 8.0)
        max_swap = getattr(self.config.performance, "max_swap_used_gb", 6.0)
        if not self.specs.supports_neutts(min_ram_gb=min_ram, max_swap_used_gb=max_swap):
            Logger.warning("Speech: NeuTTS disabled (insufficient resources or vendor/neutts missing)")
            return None

        try:
            sys.path.insert(0, str(ROOT / "vendor" / "neutts"))
            from neutts import NeuTTS
            Logger.info("Speech: NeuTTS initialized")
            return NeuTTS(
                backbone_repo="neuphonic/neutts-nano-q8-gguf",
                backbone_device="cpu",
                codec_repo="neuphonic/neucodec",
                codec_device="cpu",
            )
        except Exception as e:
            Logger.warning(f"Speech: NeuTTS init failed ({e}); falling back to gTTS")
            return None

    def synthesize(self, text: str) -> Optional[Tuple[str, bytes]]:
        """
        Synthesize text to audio.

        Returns:
            (mime_type, audio_bytes), or None on failure.
        """
        if not text:
            return None

        if self.engine is not None:
            result = self._synthesize_neutts(text)
            if result is not None:
                return result
            Logger.warning("Speech: NeuTTS synthesis failed, falling back to gTTS")

        return self._synthesize_gtts(text)

    def synthesize_async(self, text: str, callback: Callable[[Optional[Tuple[str, bytes]]], None]) -> None:
        """Synthesize text in a background thread; callback receives the result (or None)."""
        def _synth_task():
            try:
                callback(self.synthesize(text))
            except Exception as e:
                Logger.error(f"Speech: async synthesis failed: {e}")
                callback(None)

        self._executor.submit(_synth_task)

    def _synthesize_neutts(self, text: str) -> Optional[Tuple[str, bytes]]:
        try:
            ref_audio_path = ROOT / "src" / "assets" / "voice_ref.wav"
            if not ref_audio_path.exists():
                Logger.warning(f"Speech: reference audio not found at {ref_audio_path}")
                return None

            if self._ref_codes is None:
                Logger.info(f"Speech: encoding reference audio from {ref_audio_path}")
                self._ref_codes = self.engine.encode_reference(str(ref_audio_path))

            audio_array = self.engine.infer(text, self._ref_codes, NEUTTS_REF_TEXT)
            if audio_array is None or len(audio_array) == 0:
                Logger.warning("Speech: audio synthesis returned empty waveform")
                return None

            # Convert float32 [-1, 1] to int16 PCM
            audio_int16 = (audio_array * 32767).astype(np.int16)

            byte_io = io.BytesIO()
            write(byte_io, NEUTTS_SAMPLE_RATE, audio_int16)

            Logger.debug("Speech: audio synthesized with NeuTTS")
            return "audio/wav", byte_io.getvalue()
        except Exception as e:
            Logger.error(f"Speech: NeuTTS synthesis failed: {e}")
            return None

    def _synthesize_gtts(self, text: str) -> Optional[Tuple[str, bytes]]:
        try:
            # Chinese-focused: speak hanzi with the Mandarin voice, anything
            # else (e.g. English translations) falls back to English
            has_hanzi = any('\u4e00' <= ch <= '\u9fff' for ch in text)
            lang = "zh" if has_hanzi else "en"
            byte_io = io.BytesIO()
            gTTS(text, lang=lang).write_to_buff(byte_io)
            Logger.debug(f"Speech: audio synthesized with gTTS (lang={lang})")
            return "audio/mpeg", byte_io.getvalue()
        except Exception as e:
            Logger.error(f"Speech: gTTS synthesis failed: {e}")
            return None

    def close(self) -> None:
        self._executor.shutdown(wait=True)
