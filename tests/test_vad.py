"""Tests for the energy-fallback TurnDetector.

Runs without silero/torch: the detector is either forced onto the energy
path via the constructor flag, or falls back automatically because silero
is not installed in this container.
"""
from __future__ import annotations

import math
import random

import pytest

from backend.audio.vad import TurnDetector, _EnergyVAD, get_turn_detector
from backend.config import Settings

SR = 16000
FRAME_MS = 200
FRAME_BYTES = SR * FRAME_MS // 1000 * 2  # PCM16 mono


@pytest.fixture()
def settings() -> Settings:
    return Settings()  # vad: silero backend, 1000ms end-of-turn, 200ms chunks


def make_noise(duration_sec: float, amp: int = 50, seed: int = 7) -> bytes:
    rng = random.Random(seed)
    n = int(duration_sec * SR)
    return b"".join(
        int(rng.uniform(-amp, amp)).to_bytes(2, "little", signed=True) for _ in range(n)
    )


def make_tone(duration_sec: float, freq: float = 440.0, amp: int = 8000) -> bytes:
    n = int(duration_sec * SR)
    return b"".join(
        int(amp * math.sin(2.0 * math.pi * freq * i / SR)).to_bytes(2, "little", signed=True)
        for i in range(n)
    )


def feed_in_frames(det: TurnDetector, pcm: bytes) -> bytes | None:
    """Feed audio in 200ms frames; return the first completed utterance."""
    for off in range(0, len(pcm), FRAME_BYTES):
        result = det.feed(pcm[off : off + FRAME_BYTES])
        if result is not None:
            return result
    return None


class TestEnergyFallback:
    def test_falls_back_without_silero(self, settings):
        # silero-vad is not installed in this container: constructing with the
        # default "silero" backend must degrade to the energy path, not raise.
        det = get_turn_detector(settings)
        assert isinstance(det, TurnDetector)
        # Either silero genuinely loaded (target machine) or we got the fallback.
        assert det._vad is not None

    def test_detects_utterance(self, settings):
        det = TurnDetector(settings, force_fallback=True)
        assert isinstance(det._vad, _EnergyVAD)
        pcm = make_noise(0.5) + make_tone(1.0) + make_noise(1.5)
        utterance = feed_in_frames(det, pcm)
        assert utterance is not None
        duration = len(utterance) / 2 / SR
        # ~300ms lead + 1.0s speech + <=~350ms trailing padding
        assert 1.0 <= duration <= 2.2

    def test_resets_after_utterance(self, settings):
        det = TurnDetector(settings, force_fallback=True)
        pcm = make_noise(0.4) + make_tone(0.8) + make_noise(1.4)
        assert feed_in_frames(det, pcm) is not None
        # After the turn completes, plain silence yields nothing.
        assert feed_in_frames(det, make_noise(1.0, seed=11)) is None
        assert det.flush() is None
        # And a second utterance is detected fresh.
        pcm2 = make_noise(0.4, seed=13) + make_tone(0.8, freq=330.0) + make_noise(1.4, seed=17)
        assert feed_in_frames(det, pcm2) is not None

    def test_silence_only_returns_nothing(self, settings):
        det = TurnDetector(settings, force_fallback=True)
        assert feed_in_frames(det, make_noise(2.0)) is None
        assert det.flush() is None

    def test_force_flush_returns_buffer_when_no_speech_detected(self, settings):
        # Simulates a quiet mic the VAD never flags as speech: auto flush
        # yields nothing, but the user's manual "done" (force=True) must hand
        # the buffered audio to STT rather than silently dropping the answer.
        det = TurnDetector(settings, force_fallback=True)
        quiet = make_noise(1.2, amp=40)  # below the energy threshold
        assert feed_in_frames(det, quiet) is None
        assert det.flush() is None  # auto: nothing
        det2 = TurnDetector(settings, force_fallback=True)
        feed_in_frames(det2, quiet)
        forced = det2.flush(force=True)
        assert forced is not None and len(forced) > 0

    def test_auto_end_false_never_completes_on_silence(self, settings):
        # The practice tab's fix for the cut-off bug: with auto_end=False,
        # feed() must never end the turn no matter how long the trailing
        # silence runs — only a manual flush(force=True) does.
        det = TurnDetector(settings, force_fallback=True, auto_end=False)
        pcm = make_tone(1.0) + make_noise(5.0)  # speech then 5s of "silence"
        assert feed_in_frames(det, pcm) is None
        forced = det.flush(force=True)
        assert forced is not None and len(forced) > 0

    def test_flush_returns_pending_speech(self, settings):
        det = TurnDetector(settings, force_fallback=True)
        # Speech with no trailing silence: feed never completes the turn...
        pcm = make_noise(0.5) + make_tone(1.0)
        assert feed_in_frames(det, pcm) is None
        # ...but flush hands back the buffered utterance and resets.
        utterance = det.flush()
        assert utterance is not None
        assert len(utterance) / 2 / SR >= 0.9
        assert det.flush() is None

    def test_empty_feed(self, settings):
        det = TurnDetector(settings, force_fallback=True)
        assert det.feed(b"") is None
        assert det.flush() is None

    def test_buffer_cap_drops_oldest_chunks(self, settings):
        from backend.audio.vad import CHUNK_BYTES, CHUNK_MS, MAX_BUFFER_MS

        det = TurnDetector(settings, force_fallback=True, auto_end=False)
        max_chunks = int(MAX_BUFFER_MS / CHUNK_MS)
        # Pre-fill past the cap directly (avoids synthesizing megabytes of audio).
        det._chunks = [(b"\x00" * CHUNK_BYTES, False)] * (max_chunks + 50)
        det._process_chunk(b"\x00" * CHUNK_BYTES)
        assert len(det._chunks) <= max_chunks
