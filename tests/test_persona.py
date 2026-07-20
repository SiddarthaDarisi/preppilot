"""Tests for the interviewer persona knob — a candidate-facing tone line
injected into the interviewer SYSTEM prompt (backend/prompts/interviewer.py).
Coaching/scoring stays unaffected; this only changes the LLM's phrasing."""
from __future__ import annotations

from backend.prompts.interviewer import build_interviewer_turn


def _session_meta(persona: str) -> dict:
    return {
        "role": "Software Engineer",
        "seniority": "mid",
        "jd_text": "",
        "focus_areas": ["behavioral"],
        "persona": persona,
    }


class TestPersona:
    def test_neutral_persona_adds_no_extra_line(self):
        system, _ = build_interviewer_turn(_session_meta("neutral"), [], None)
        assert "PERSONA:" not in system

    def test_friendly_persona_line_present(self):
        system, _ = build_interviewer_turn(_session_meta("friendly"), [], None)
        assert "PERSONA:" in system
        assert "warm" in system.lower()

    def test_tough_persona_line_present(self):
        system, _ = build_interviewer_turn(_session_meta("tough"), [], None)
        assert "PERSONA:" in system
        assert "skeptical" in system.lower()

    def test_missing_persona_key_defaults_to_neutral(self):
        meta = _session_meta("neutral")
        del meta["persona"]
        system, _ = build_interviewer_turn(meta, [], None)
        assert "PERSONA:" not in system
