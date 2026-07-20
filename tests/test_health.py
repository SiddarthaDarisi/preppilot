"""Tests for build_health_flags() — the pure core of GET /api/health.

Guards against the exact failure mode reported by a real user: launching
with system Python (no voice deps) gave zero indication anything was wrong
until "zero word count" showed up in delivery feedback minutes later.
"""
from __future__ import annotations

from backend.config import Settings
from backend.main import build_health_flags


class TestBuildHealthFlags:
    def test_all_missing_flags_run_ps1_hint(self, monkeypatch):
        monkeypatch.setattr("backend.main._module_available", lambda name: False)
        settings = Settings()
        degraded, flags = build_health_flags(settings, provider_name=settings.llm.provider)

        assert flags == {
            "demo_llm": False,
            "stt_missing": True,
            "vad_missing": True,
            "tts_missing": True,
        }
        probe_msgs = [d for d in degraded if "package missing" in d]
        assert len(probe_msgs) == 3
        assert all("run.ps1" in d for d in probe_msgs)

    def test_all_available_no_probe_degradation(self, monkeypatch):
        monkeypatch.setattr("backend.main._module_available", lambda name: True)
        settings = Settings()
        degraded, flags = build_health_flags(settings, provider_name=settings.llm.provider)

        assert flags == {
            "demo_llm": False,
            "stt_missing": False,
            "vad_missing": False,
            "tts_missing": False,
        }
        assert not any("package missing" in d for d in degraded)

    def test_demo_llm_flag_when_fallen_back_to_fake(self, monkeypatch):
        monkeypatch.setattr("backend.main._module_available", lambda name: True)
        settings = Settings()
        assert settings.llm.provider == "ollama"  # default config
        degraded, flags = build_health_flags(settings, provider_name="fake")

        assert flags["demo_llm"] is True
        assert any("DEMO MODE" in d for d in degraded)

    def test_stt_disabled_by_config_is_not_missing(self, monkeypatch):
        monkeypatch.setattr("backend.main._module_available", lambda name: False)
        settings = Settings()
        settings.stt.backend = "none"
        degraded, flags = build_health_flags(settings, provider_name=settings.llm.provider)

        assert flags["stt_missing"] is False
        assert any("stt: disabled (text mode only)" in d for d in degraded)
        assert not any("stt:" in d and "package missing" in d for d in degraded)

    def test_fake_provider_configured_is_not_demo_mode(self, monkeypatch):
        """Explicitly asking for the fake provider (e.g. run.ps1 -Fake) is not
        an unintended fallback — no DEMO MODE warning should fire."""
        monkeypatch.setattr("backend.main._module_available", lambda name: True)
        settings = Settings()
        settings.llm.provider = "fake"
        degraded, flags = build_health_flags(settings, provider_name="fake")

        assert flags["demo_llm"] is False
        assert not any("DEMO MODE" in d for d in degraded)
