"""Tests for the Scores clamp validator (backend/schemas.py).

Guards against qwen3:8b (and other local models) occasionally emitting a 0
or out-of-range score despite the 1-10 prompt instruction — previously this
raised a ValidationError that aborted the whole turn (see CLAUDE.md /
orchestrator ProviderError handling).
"""
from __future__ import annotations

import pytest

from backend.schemas import FeedbackResult, Scores


class TestScoresClamp:
    def test_zero_clamps_to_one(self):
        s = Scores(content_relevance=0, structure=0, specificity=0, delivery=0, overall=0)
        assert s.content_relevance == 1
        assert s.structure == 1
        assert s.specificity == 1
        assert s.delivery == 1
        assert s.overall == 1

    def test_eleven_clamps_to_ten(self):
        s = Scores(content_relevance=11, structure=100, specificity=10, delivery=10, overall=10)
        assert s.content_relevance == 10
        assert s.structure == 10

    def test_float_rounds(self):
        s = Scores(overall=7.6)
        assert s.overall == 8

    def test_negative_clamps_to_one(self):
        s = Scores(overall=-5)
        assert s.overall == 1

    def test_technical_accuracy_none_passes_through(self):
        s = Scores(technical_accuracy=None)
        assert s.technical_accuracy is None

    def test_technical_accuracy_zero_clamps_not_rejected(self):
        s = Scores(technical_accuracy=0)
        assert s.technical_accuracy == 1

    def test_in_range_values_unchanged(self):
        s = Scores(content_relevance=7, structure=3, specificity=5, delivery=6, overall=4)
        assert (s.content_relevance, s.structure, s.specificity, s.delivery, s.overall) == (7, 3, 5, 6, 4)

    def test_feedback_result_round_trip_with_zero_scores(self):
        """The exact failure mode from the bug report: an LLM-shaped dict with
        0 scores must validate instead of raising."""
        payload = {
            "scores": {
                "content_relevance": 0,
                "structure": 0,
                "specificity": 0,
                "technical_accuracy": 0,
                "delivery": 0,
                "overall": 0,
            },
            "star_completeness": {"situation": True, "task": False, "action": True, "result": False},
            "strengths": ["Clear communication"],
            "improvements": [{"issue": "Too vague", "fix": "Add specific metrics"}],
            "delivery_feedback": "Spoke too fast.",
            "coaching_summary": "Solid attempt, needs more specifics.",
        }
        result = FeedbackResult.model_validate(payload)
        assert result.scores.overall == 1
        assert result.scores.technical_accuracy == 1

    def test_non_numeric_score_still_raises(self):
        with pytest.raises(Exception):
            Scores(overall="not a number")
