"""Prosody (pitch + energy) extraction with graceful degradation.

Preferred pitch backend: praat-parselmouth (Praat's autocorrelation pitch
tracker). Fallback: librosa.pyin. Energy: RMS over 25 ms frames via librosa
when present, plain numpy otherwise. With neither pitch backend (or without
numpy) a zeros dict with ``available: False`` is returned — never raises.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("preppilot.analytics")

_warned: set[str] = set()

_ZEROS: dict[str, Any] = {
    "pitch_mean_hz": 0.0,
    "pitch_std_hz": 0.0,
    "pitch_range_hz": 0.0,
    "energy_cv": 0.0,
    "voiced_ratio": 0.0,
    "available": False,
}

PITCH_FLOOR_HZ = 60.0
PITCH_CEILING_HZ = 400.0
FRAME_MS = 25.0


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg)


def _pitch_parselmouth(y: Any, sample_rate: int, np: Any) -> tuple[Any, Any] | None:
    """Return (voiced_f0, total_frame_count) via Praat, or None if unavailable."""
    try:
        import parselmouth  # noqa: PLC0415 (lazy)
    except Exception as exc:
        _warn_once("parselmouth", f"parselmouth unavailable ({exc.__class__.__name__}); trying librosa.pyin")
        return None
    try:
        snd = parselmouth.Sound(y.astype(np.float64), sampling_frequency=sample_rate)
        pitch = snd.to_pitch(pitch_floor=PITCH_FLOOR_HZ, pitch_ceiling=PITCH_CEILING_HZ)
        f0 = pitch.selected_array["frequency"]
        voiced = f0[f0 > 0]
        return voiced, len(f0)
    except Exception as exc:
        _warn_once("parselmouth-run", f"parselmouth pitch extraction failed: {exc}; trying librosa.pyin")
        return None


def _pitch_pyin(y: Any, sample_rate: int, np: Any) -> tuple[Any, Any] | None:
    try:
        import librosa  # noqa: PLC0415 (lazy)
    except Exception as exc:
        _warn_once("librosa-pitch", f"librosa unavailable ({exc.__class__.__name__}); no pitch backend")
        return None
    try:
        f0, _, _ = librosa.pyin(
            y, fmin=PITCH_FLOOR_HZ, fmax=PITCH_CEILING_HZ, sr=sample_rate
        )
        voiced = f0[np.isfinite(f0)]
        return voiced, len(f0)
    except Exception as exc:
        _warn_once("pyin-run", f"librosa.pyin failed: {exc}; no pitch backend")
        return None


def _energy_cv(y: Any, sample_rate: int, np: Any) -> float:
    """Coefficient of variation of frame RMS over active (above-floor) frames."""
    frame_length = max(1, int(sample_rate * FRAME_MS / 1000.0))
    hop = max(1, frame_length // 2)
    try:
        import librosa  # noqa: PLC0415 (lazy)

        rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop)[0]
    except Exception:
        n_frames = max(0, 1 + (len(y) - frame_length) // hop)
        if n_frames == 0:
            return 0.0
        rms = np.array(
            [
                float(np.sqrt(np.mean(y[i * hop : i * hop + frame_length] ** 2)))
                for i in range(n_frames)
            ]
        )
    if rms.size == 0:
        return 0.0
    # Noise floor: ignore near-silent frames so pauses don't dominate the CV.
    floor = max(float(np.max(rms)) * 0.05, 1e-6)
    active = rms[rms > floor]
    if active.size == 0 or float(np.mean(active)) <= 0:
        return 0.0
    return float(np.std(active) / np.mean(active))


def extract_prosody(pcm16: bytes, sample_rate: int) -> dict[str, Any]:
    """Extract pitch/energy features from PCM16 mono audio.

    Returns a dict with pitch_mean_hz, pitch_std_hz, pitch_range_hz (5th-95th
    percentile of voiced F0), energy_cv, voiced_ratio, and ``available``.
    """
    if not pcm16 or sample_rate <= 0:
        return dict(_ZEROS)
    try:
        import numpy as np  # noqa: PLC0415 (lazy)
    except Exception as exc:
        _warn_once("numpy", f"numpy unavailable ({exc.__class__.__name__}); prosody disabled")
        return dict(_ZEROS)

    y = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if y.size == 0:
        return dict(_ZEROS)

    pitch = _pitch_parselmouth(y, sample_rate, np) or _pitch_pyin(y, sample_rate, np)
    if pitch is None:
        return dict(_ZEROS)

    voiced, total_frames = pitch
    result = dict(_ZEROS)
    result["available"] = True
    result["energy_cv"] = _energy_cv(y, sample_rate, np)
    if total_frames > 0:
        result["voiced_ratio"] = float(len(voiced) / total_frames)
    if len(voiced) > 0:
        result["pitch_mean_hz"] = float(np.mean(voiced))
        result["pitch_std_hz"] = float(np.std(voiced))
        p5, p95 = np.percentile(voiced, [5, 95])
        result["pitch_range_hz"] = float(p95 - p5)
    return result
