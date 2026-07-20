"""Tests for filler counting and delivery-metric computation.

Must pass in a container with NO heavy deps (torch/faster-whisper/kokoro)
and with or without the optional prosody libs (librosa/parselmouth).
"""
from __future__ import annotations

import array
import math

import pytest

from backend.analytics import fillers, metrics
from backend.config import Settings
from backend.schemas import DeliveryMetrics, TranscriptionResult, WordTiming


@pytest.fixture()
def settings() -> Settings:
    return Settings()


def make_sine_pcm(duration_sec: float, sample_rate: int = 16000, freq: float = 440.0, amp: int = 8000) -> bytes:
    n = int(duration_sec * sample_rate)
    samples = array.array(
        "h", (int(amp * math.sin(2.0 * math.pi * freq * i / sample_rate)) for i in range(n))
    )
    return samples.tobytes()


# ------------------------------------------------------------------ fillers

class TestFillers:
    def test_feel_like_is_not_a_filler(self):
        total, breakdown = fillers.count_fillers("I feel like this is fine")
        assert "like" not in breakdown
        assert total == 0

    def test_looks_like_is_not_a_filler(self):
        total, breakdown = fillers.count_fillers("It looks like rain today")
        assert "like" not in breakdown

    def test_filler_like_counts(self):
        total, breakdown = fillers.count_fillers("And then like the server like crashed")
        assert breakdown.get("like") == 2

    def test_classic_filler_sentence(self):
        total, breakdown = fillers.count_fillers("Um, so basically it was, you know, hard")
        assert breakdown.get("um") == 1
        assert breakdown.get("basically") == 1
        assert breakdown.get("you know") == 1
        assert total >= 3

    def test_sentence_initial_so(self):
        total, breakdown = fillers.count_fillers("So I started. So then we shipped it.")
        assert breakdown.get("so") == 2
        # non-initial "so" does not count
        total2, breakdown2 = fillers.count_fillers("It was so difficult")
        assert "so" not in breakdown2

    def test_trailing_right_tag(self):
        _, breakdown = fillers.count_fillers("That makes sense, right? We did the right thing.")
        assert breakdown.get("right") == 1

    def test_phrase_fillers_and_hesitations(self):
        text = "Uh, I mean, it was kind of tricky, sort of a mess, hmm, er, actually"
        total, breakdown = fillers.count_fillers(text)
        for key in ("uh", "i mean", "kind of", "sort of", "hmm", "er", "actually"):
            assert breakdown.get(key) == 1, key
        assert total == 7

    def test_case_insensitive_and_elongations(self):
        total, breakdown = fillers.count_fillers("UMM yeah UH huh Hmmm")
        assert breakdown.get("um") == 1
        assert breakdown.get("uh") == 1
        assert breakdown.get("hmm") == 1

    def test_empty_text(self):
        assert fillers.count_fillers("") == (0, {})


# ------------------------------------------------------------- text metrics

class TestTextMetrics:
    def test_clean_text_full_confidence(self):
        m = metrics.compute_text_metrics("I led the migration and reduced latency by forty percent")
        assert isinstance(m, DeliveryMetrics)
        assert m.filler_count == 0
        assert m.confidence_proxy == 100.0
        assert m.word_count == 10
        assert m.wpm == 0.0  # no timing in text mode

    def test_filler_heavy_text_penalized(self):
        m = metrics.compute_text_metrics("Um, so basically it was, you know, hard")
        assert m.word_count == 8
        assert m.filler_count >= 3
        assert 0.0 <= m.confidence_proxy < 100.0
        # filler_rate 3/8 caps the filler penalty at 30
        assert m.confidence_proxy == 70.0

    def test_empty_text(self):
        m = metrics.compute_text_metrics("")
        assert m.word_count == 0
        assert m.filler_count == 0
        assert 0.0 <= m.confidence_proxy <= 100.0


# --------------------------------------------------------- delivery metrics

def _synthetic_transcription() -> TranscriptionResult:
    """10 words, one 0.5s pause and one 2.0s long pause, total 6.2s."""
    starts = [0.0, 0.4, 1.2, 1.6, 3.9, 4.3, 4.7, 5.1, 5.5, 5.9]
    words = [
        WordTiming(word=w, start=s, end=round(s + 0.3, 2))
        for w, s in zip(
            ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"],
            starts,
        )
    ]
    return TranscriptionResult(
        text="one two three four five six seven eight nine ten",
        words=words,
        duration_sec=6.2,
    )


class TestDeliveryMetrics:
    def test_synthetic_answer(self, settings):
        tr = _synthetic_transcription()
        pcm = make_sine_pcm(6.2)
        m = metrics.compute_delivery_metrics(pcm, 16000, tr, settings)
        assert isinstance(m, DeliveryMetrics)
        assert m.word_count == 10
        assert m.duration_sec == pytest.approx(6.2, abs=0.01)
        # wpm = 10 / (6.2 / 60)
        assert m.wpm == pytest.approx(96.8, abs=0.2)
        # speaking time = 10 * 0.3 s -> articulation 200 wpm
        assert m.articulation_wpm == pytest.approx(200.0, abs=1.0)
        # pauses: gaps of 0.5s and 2.0s
        assert m.long_pause_count == 1
        assert m.pause_ratio == pytest.approx(2.5 / 6.2, abs=0.01)
        assert m.filler_count == 0
        # penalties: -8 long pause, ~-9.2 pause ratio, ~-6.6 pace,
        # possibly -10 monotone if a prosody backend is installed
        assert 50.0 <= m.confidence_proxy <= 90.0

    def test_prosody_unavailable_still_valid(self, settings, monkeypatch):
        monkeypatch.setattr(
            metrics.prosody,
            "extract_prosody",
            lambda pcm, sr: {
                "pitch_mean_hz": 0.0,
                "pitch_std_hz": 0.0,
                "pitch_range_hz": 0.0,
                "energy_cv": 0.0,
                "voiced_ratio": 0.0,
                "available": False,
            },
        )
        tr = _synthetic_transcription()
        m = metrics.compute_delivery_metrics(make_sine_pcm(6.2), 16000, tr, settings)
        assert isinstance(m, DeliveryMetrics)
        assert m.pitch_mean_hz == 0.0
        assert m.pitch_std_hz == 0.0
        assert m.energy_cv == 0.0
        # no monotone penalty when pitch is unavailable
        assert m.confidence_proxy == pytest.approx(100.0 - 8.0 - 9.2 - 6.6, abs=0.5)
        assert 0.0 <= m.confidence_proxy <= 100.0

    def test_empty_transcription_falls_back_to_pcm_duration(self, settings):
        tr = TranscriptionResult(text="", words=[], duration_sec=0.0)
        m = metrics.compute_delivery_metrics(make_sine_pcm(2.0), 16000, tr, settings)
        assert m.duration_sec == pytest.approx(2.0, abs=0.01)
        assert m.word_count == 0
        assert m.wpm == 0.0
        assert 0.0 <= m.confidence_proxy <= 100.0

    def test_ser_disabled_by_default(self, settings):
        tr = _synthetic_transcription()
        m = metrics.compute_delivery_metrics(make_sine_pcm(1.0), 16000, tr, settings)
        assert m.ser_label is None
        assert m.ser_confidence is None

    def test_confidence_always_clamped(self, settings):
        # Pathological answer: nothing but fillers and long pauses.
        words = [
            WordTiming(word="um", start=float(i * 3), end=float(i * 3) + 0.2) for i in range(10)
        ]
        tr = TranscriptionResult(text=" ".join(["um"] * 10), words=words, duration_sec=30.0)
        m = metrics.compute_delivery_metrics(b"", 16000, tr, settings)
        assert 0.0 <= m.confidence_proxy <= 100.0


class TestExpressiveness:
    def test_full_pitch_and_energy_maxes_out(self):
        assert metrics._expressiveness(
            pitch_std_hz=35.0, pitch_range_hz=120.0, energy_cv=0.35, pitch_available=True
        ) == pytest.approx(100.0)

    def test_no_pitch_no_energy_is_zero(self):
        assert metrics._expressiveness(
            pitch_std_hz=0.0, pitch_range_hz=0.0, energy_cv=0.0, pitch_available=False
        ) == 0.0

    def test_pitch_unavailable_only_energy_term_counts(self):
        # Even with nonzero pitch numbers, pitch_available=False must zero
        # those terms out (mirrors compute_delivery_metrics's own gating).
        v = metrics._expressiveness(
            pitch_std_hz=35.0, pitch_range_hz=120.0, energy_cv=0.35, pitch_available=False
        )
        assert v == pytest.approx(25.0)

    def test_mid_values_scale_linearly(self):
        v = metrics._expressiveness(
            pitch_std_hz=17.5, pitch_range_hz=60.0, energy_cv=0.175, pitch_available=True
        )
        assert v == pytest.approx(50.0)

    def test_clamped_above_100(self):
        v = metrics._expressiveness(
            pitch_std_hz=1000.0, pitch_range_hz=1000.0, energy_cv=10.0, pitch_available=True
        )
        assert v == 100.0

    def test_text_metrics_expressiveness_is_zero(self):
        assert metrics.compute_text_metrics("hello world").expressiveness == 0.0
