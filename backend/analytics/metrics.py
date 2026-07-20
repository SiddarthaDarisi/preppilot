"""Delivery-metrics aggregation: pace, pauses, fillers, prosody, SER.

Everything degrades gracefully — with no audio libs installed the metrics
still populate from the transcript alone.
"""
from __future__ import annotations

import logging
from typing import Any

from backend import schemas
from backend.analytics import fillers, prosody, ser

logger = logging.getLogger("preppilot.analytics")

PAUSE_GAP_SEC = 0.3        # inter-word gap counted as a pause
LONG_PAUSE_SEC = 1.5       # gap counted as a long pause
MONOTONE_PITCH_STD_HZ = 15.0

EXPR_PITCH_STD_FULL_HZ = 35.0     # pitch std that earns full pitch-variation credit
EXPR_PITCH_RANGE_FULL_HZ = 120.0  # pitch range that earns full pitch-range credit
EXPR_ENERGY_CV_FULL = 0.35        # energy (loudness) coefficient of variation for full credit


def _confidence_proxy(
    filler_rate: float,
    long_pause_count: int,
    pause_ratio: float,
    wpm: float | None,
    wpm_range: tuple[int, int],
    pitch_std_hz: float | None,
) -> float:
    """Transparent 0-100 composite. See compute_delivery_metrics docstring."""
    score = 100.0
    score -= min(30.0, 900.0 * max(0.0, filler_rate - 0.02))
    score -= min(20.0, 8.0 * long_pause_count)
    score -= min(20.0, 60.0 * max(0.0, pause_ratio - 0.25))
    if wpm is not None and wpm > 0:
        lo, hi = wpm_range
        distance = max(0.0, lo - wpm, wpm - hi)
        score -= min(15.0, 0.5 * distance)
    if pitch_std_hz is not None and pitch_std_hz < MONOTONE_PITCH_STD_HZ:
        score -= 10.0
    return max(0.0, min(100.0, score))


def _expressiveness(
    pitch_std_hz: float,
    pitch_range_hz: float,
    energy_cv: float,
    pitch_available: bool,
) -> float:
    """Transparent 0-100 tone-variety composite (NOT an emotion label):

        pitch-variation term:  min(45, 45 * pitch_std_hz / 35)      (0 if no pitch)
        pitch-range term:      min(30, 30 * pitch_range_hz / 120)   (0 if no pitch)
        energy-variation term: min(25, 25 * energy_cv / 0.35)
        clamp to [0, 100]

    Returns 0.0 when neither pitch nor energy data is available (text mode).
    Higher = more vocal variety (pitch + loudness); this says nothing about
    which emotion is being expressed, only how monotone-vs-varied the
    delivery is — same interpretability rule as confidence_proxy above.
    """
    score = 0.0
    if pitch_available:
        score += min(45.0, 45.0 * pitch_std_hz / EXPR_PITCH_STD_FULL_HZ)
        score += min(30.0, 30.0 * pitch_range_hz / EXPR_PITCH_RANGE_FULL_HZ)
    score += min(25.0, 25.0 * energy_cv / EXPR_ENERGY_CV_FULL)
    return max(0.0, min(100.0, score))


def compute_delivery_metrics(
    pcm16: bytes,
    sample_rate: int,
    transcription: schemas.TranscriptionResult,
    settings: Any,
) -> schemas.DeliveryMetrics:
    """Compute per-answer delivery metrics from audio + transcription.

    confidence_proxy (0-100) — transparent weighted formula:

        score = 100
        score -= min(30, 900 * max(0, filler_rate - 0.02))     # fillers over 2%
        score -= min(20, 8 * long_pause_count)                 # pauses > 1.5s
        score -= min(20, 60 * max(0, pause_ratio - 0.25))      # >25% silence
        score -= min(15, 0.5 * dist(wpm outside wpm_range))    # pace, default [110, 160]
        score -= 10 if pitch_std_hz < 15 (and pitch available) # monotone
        clamp to [0, 100]
    """
    text = transcription.text or ""
    words = transcription.words or []

    # Duration: prefer whisper's, fall back to raw PCM length.
    pcm_duration = len(pcm16) / 2.0 / sample_rate if sample_rate > 0 else 0.0
    duration_sec = transcription.duration_sec or pcm_duration

    word_count = len(words) if words else len(text.split())

    # Pace.
    wpm = word_count / (duration_sec / 60.0) if duration_sec > 0 else 0.0
    speaking_time = sum(max(0.0, w.end - w.start) for w in words) if words else duration_sec
    articulation_wpm = word_count / (speaking_time / 60.0) if speaking_time > 0 else 0.0

    # Pauses from inter-word gaps.
    pause_time = 0.0
    long_pause_count = 0
    for prev, nxt in zip(words, words[1:]):
        gap = nxt.start - prev.end
        if gap > PAUSE_GAP_SEC:
            pause_time += gap
        if gap > LONG_PAUSE_SEC:
            long_pause_count += 1
    pause_ratio = pause_time / duration_sec if duration_sec > 0 else 0.0

    # Fillers.
    filler_count, filler_words = fillers.count_fillers(text)
    filler_rate = filler_count / max(word_count, 1)

    # Prosody (graceful zeros when unavailable).
    pros = prosody.extract_prosody(pcm16, sample_rate)
    pitch_available = bool(pros.get("available")) and pros.get("pitch_mean_hz", 0.0) > 0

    # Optional SER.
    ser_label, ser_confidence = (None, None)
    if getattr(settings.analytics, "use_ser", False):
        ser_label, ser_confidence = ser.classify(pcm16, sample_rate, settings)

    wpm_range = tuple(settings.analytics.wpm_range)
    confidence = _confidence_proxy(
        filler_rate=filler_rate,
        long_pause_count=long_pause_count,
        pause_ratio=pause_ratio,
        wpm=wpm if duration_sec > 0 else None,
        wpm_range=wpm_range,  # type: ignore[arg-type]
        pitch_std_hz=pros["pitch_std_hz"] if pitch_available else None,
    )
    expressiveness = _expressiveness(
        pitch_std_hz=pros["pitch_std_hz"],
        pitch_range_hz=pros["pitch_range_hz"],
        energy_cv=pros["energy_cv"],
        pitch_available=pitch_available,
    )

    return schemas.DeliveryMetrics(
        wpm=round(wpm, 1),
        articulation_wpm=round(articulation_wpm, 1),
        pause_ratio=round(pause_ratio, 3),
        long_pause_count=long_pause_count,
        filler_count=filler_count,
        filler_rate=round(filler_rate, 4),
        filler_words=filler_words,
        pitch_mean_hz=round(pros["pitch_mean_hz"], 1),
        pitch_std_hz=round(pros["pitch_std_hz"], 1),
        pitch_range_hz=round(pros["pitch_range_hz"], 1),
        energy_cv=round(pros["energy_cv"], 3),
        duration_sec=round(duration_sec, 2),
        word_count=word_count,
        confidence_proxy=round(confidence, 1),
        expressiveness=round(expressiveness, 1),
        ser_label=ser_label,
        ser_confidence=ser_confidence,
    )


def compute_text_metrics(text: str) -> schemas.DeliveryMetrics:
    """Text-only metrics: fillers + word count; no timing or prosody.

    confidence_proxy uses only the filler term of the composite:
    ``100 - min(30, 900 * max(0, filler_rate - 0.02))``.
    """
    text = text or ""
    word_count = len(text.split())
    filler_count, filler_words = fillers.count_fillers(text)
    filler_rate = filler_count / max(word_count, 1)
    confidence = max(0.0, min(100.0, 100.0 - min(30.0, 900.0 * max(0.0, filler_rate - 0.02))))
    return schemas.DeliveryMetrics(
        filler_count=filler_count,
        filler_rate=round(filler_rate, 4),
        filler_words=filler_words,
        word_count=word_count,
        confidence_proxy=round(confidence, 1),
    )
