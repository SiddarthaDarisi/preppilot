"""Optional speech-emotion recognition (SER) via wav2vec2.

Model: ``superb/wav2vec2-base-superb-er`` — trained on *acted* IEMOCAP data,
so treat the output as a weak secondary signal only, never a primary metric.
Gated by ``analytics.use_ser`` in config; disabled or missing deps
(transformers/torch) → ``(None, None)``. All heavy imports are lazy.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("preppilot.analytics")

MODEL_ID = "superb/wav2vec2-base-superb-er"
TARGET_SR = 16000

_warned: set[str] = set()
_pipeline: Any = None
_pipeline_failed = False


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg)


def _get_pipeline() -> Any:
    global _pipeline, _pipeline_failed
    if _pipeline is not None or _pipeline_failed:
        return _pipeline
    try:
        from transformers import pipeline  # noqa: PLC0415 (lazy)

        _pipeline = pipeline("audio-classification", model=MODEL_ID)
    except Exception as exc:
        _pipeline_failed = True
        _warn_once("ser", f"SER unavailable ({exc.__class__.__name__}: {exc}); returning (None, None)")
    return _pipeline


def _resample_to_16k(y: Any, sample_rate: int, np: Any) -> Any:
    if sample_rate == TARGET_SR:
        return y
    try:
        import librosa  # noqa: PLC0415 (lazy)

        return librosa.resample(y, orig_sr=sample_rate, target_sr=TARGET_SR)
    except Exception:
        # Linear-interpolation fallback — fine for a weak signal.
        n_out = int(round(len(y) * TARGET_SR / sample_rate))
        if n_out <= 1 or len(y) <= 1:
            return y
        x_old = np.linspace(0.0, 1.0, num=len(y))
        x_new = np.linspace(0.0, 1.0, num=n_out)
        return np.interp(x_new, x_old, y).astype(np.float32)


def classify(
    pcm16: bytes, sample_rate: int, settings: Any = None
) -> tuple[Optional[str], Optional[float]]:
    """Classify emotion from PCM16 audio. Returns (label, confidence) or (None, None).

    Disabled when ``settings.analytics.use_ser`` is False, when audio is
    empty, or when transformers/torch are not installed.
    """
    if settings is not None and not settings.analytics.use_ser:
        return None, None
    if not pcm16 or sample_rate <= 0:
        return None, None
    pipe = _get_pipeline()
    if pipe is None:
        return None, None
    try:
        import numpy as np  # noqa: PLC0415 (lazy)

        y = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        y = _resample_to_16k(y, sample_rate, np)
        results = pipe({"array": y, "sampling_rate": TARGET_SR})
        if not results:
            return None, None
        top = max(results, key=lambda r: r.get("score", 0.0))
        return str(top.get("label")), float(top.get("score", 0.0))
    except Exception as exc:
        logger.error("SER classification failed: %s", exc)
        return None, None
