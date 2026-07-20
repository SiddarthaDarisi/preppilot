"""Tests for the on-disk TTS cache (backend/audio/tts_cache.py). Pure stdlib
— no kokoro/torch needed; uses a fake WAV blob and a temp cache dir."""
from __future__ import annotations

import pytest

from backend.audio import tts_cache


@pytest.fixture(autouse=True)
def temp_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path / "tts_cache")
    yield


class TestCacheRoundTrip:
    def test_miss_then_store_then_hit(self):
        assert tts_cache.get_cached_wav("am_adam", "Tell me about yourself.") is None
        tts_cache.store_wav("am_adam", "Tell me about yourself.", b"FAKEWAVBYTES")
        assert tts_cache.get_cached_wav("am_adam", "Tell me about yourself.") == b"FAKEWAVBYTES"

    def test_different_voice_is_a_different_key(self):
        tts_cache.store_wav("am_adam", "Same question?", b"VOICE_A")
        assert tts_cache.get_cached_wav("af_bella", "Same question?") is None
        tts_cache.store_wav("af_bella", "Same question?", b"VOICE_B")
        assert tts_cache.get_cached_wav("am_adam", "Same question?") == b"VOICE_A"
        assert tts_cache.get_cached_wav("af_bella", "Same question?") == b"VOICE_B"

    def test_whitespace_normalized_before_hashing(self):
        tts_cache.store_wav("am_adam", "  Trimmed?  ", b"X")
        assert tts_cache.get_cached_wav("am_adam", "Trimmed?") == b"X"

    def test_key_is_stable(self):
        k1 = tts_cache._cache_key("am_adam", "Question one?")
        k2 = tts_cache._cache_key("am_adam", "Question one?")
        assert k1 == k2
        assert k1 != tts_cache._cache_key("am_adam", "Question two?")


class TestSynthCached:
    def test_cache_hit_skips_synthesizer(self):
        tts_cache.store_wav("am_adam", "Cached already?", b"FROM_CACHE")

        class ExplodingSynth:
            def synth(self, text):
                raise AssertionError("synth() should not be called on a cache hit")

        result = tts_cache.synth_cached(ExplodingSynth(), "am_adam", "Cached already?")
        assert result == b"FROM_CACHE"

    def test_cache_miss_calls_synth_and_stores_result(self):
        calls = []

        class RecordingSynth:
            def synth(self, text, voice=None):
                calls.append((text, voice))
                return b"FRESH_AUDIO"

        result = tts_cache.synth_cached(RecordingSynth(), "am_adam", "Brand new question?")
        assert result == b"FRESH_AUDIO"
        # The cache key's voice is forwarded to synth() so key and audio agree.
        assert calls == [("Brand new question?", "am_adam")]
        # Second call is now a cache hit.
        result2 = tts_cache.synth_cached(RecordingSynth(), "am_adam", "Brand new question?")
        assert result2 == b"FRESH_AUDIO"
        assert calls == [("Brand new question?", "am_adam")]  # not called again

    def test_synth_returning_none_is_not_cached(self):
        class SilentSynth:
            def synth(self, text, voice=None):
                return None

        assert tts_cache.synth_cached(SilentSynth(), "am_adam", "Unsynthesizable?") is None
        assert tts_cache.get_cached_wav("am_adam", "Unsynthesizable?") is None
