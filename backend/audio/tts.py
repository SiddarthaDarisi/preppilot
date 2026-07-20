"""Text-to-speech via Kokoro (24 kHz), with graceful degradation.

Kokoro/torch are only expected on the target machine. Missing deps or
backend "none" → synth() returns None and the caller skips audio.
"""
from __future__ import annotations

import io
import logging
import struct
import threading
import wave
from typing import Any, Optional

logger = logging.getLogger("preppilot.audio")

SAMPLE_RATE = 24000

_warned: set[str] = set()
_lock = threading.Lock()
_pipeline: Any = None
_pipeline_lang: Optional[str] = None
_synthesizer: Optional["Synthesizer"] = None


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg)


def _get_pipeline(lang_code: str) -> Any:
    global _pipeline, _pipeline_lang
    with _lock:
        if _pipeline is not None and _pipeline_lang == lang_code:
            return _pipeline
        try:
            from kokoro import KPipeline  # noqa: PLC0415 (lazy)
        except Exception as exc:
            _warn_once(
                "kokoro",
                f"kokoro unavailable ({exc.__class__.__name__}: {exc}); TTS disabled",
            )
            return None
        try:
            _pipeline = KPipeline(lang_code=lang_code)
            _pipeline_lang = lang_code
            return _pipeline
        except Exception as exc:
            _warn_once("kokoro-init", f"kokoro pipeline init failed: {exc}; TTS disabled")
            return None


def _to_float_list(audio: Any) -> list[float]:
    """Normalize a kokoro audio segment (torch tensor / numpy array) to floats."""
    if hasattr(audio, "detach"):  # torch tensor
        audio = audio.detach().cpu().numpy()
    if hasattr(audio, "tolist"):
        return list(audio.tolist())
    return list(audio)


def _floats_to_wav(samples: list[float], sample_rate: int = SAMPLE_RATE) -> bytes:
    """float32 [-1, 1] → 16-bit mono WAV file bytes."""
    try:
        import numpy as np  # noqa: PLC0415 (lazy)

        arr = np.asarray(samples, dtype=np.float32)
        pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    except Exception:
        clipped = (max(-1.0, min(1.0, s)) for s in samples)
        pcm = struct.pack(f"<{len(samples)}h", *(int(s * 32767.0) for s in clipped))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class Synthesizer:
    """Synthesizes speech; returns 16-bit 24 kHz WAV bytes or None."""

    def __init__(self, settings: Any) -> None:
        self._tts_cfg = settings.tts

    def synth(self, text: str, voice: Optional[str] = None) -> Optional[bytes]:
        """`voice` overrides the configured voice for this one call (used by
        the settings drawer's voice preview and by synth_cached, which must
        keep its cache key and the produced audio in agreement)."""
        if self._tts_cfg.backend != "kokoro":
            _warn_once("tts-none", f"TTS backend '{self._tts_cfg.backend}' — no audio synthesized")
            return None
        if not text or not text.strip():
            return None
        pipeline = _get_pipeline(self._tts_cfg.lang_code)
        if pipeline is None:
            return None
        try:
            samples: list[float] = []
            for item in pipeline(text, voice=voice or self._tts_cfg.voice):
                audio = getattr(item, "audio", None)
                if audio is None and isinstance(item, (tuple, list)) and len(item) >= 3:
                    audio = item[2]
                if audio is None:
                    continue
                samples.extend(_to_float_list(audio))
            if not samples:
                return None
            return _floats_to_wav(samples)
        except Exception as exc:
            logger.error("TTS synthesis failed: %s", exc)
            return None


def get_synthesizer(settings: Any) -> Synthesizer:
    """Module-level singleton (pipeline is also cached)."""
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = Synthesizer(settings)
    return _synthesizer
