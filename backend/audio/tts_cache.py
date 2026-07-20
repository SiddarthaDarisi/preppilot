"""On-disk cache for synthesized question audio.

Interview questions repeat constantly across sessions (Adaptive mode reuses
the bank; Drill mode repeats on purpose), so synthesizing the same text
twice is pure waste — cache the WAV once and every later session gets the
interviewer's voice back in milliseconds instead of a multi-second Kokoro
call. Pure stdlib (hashlib/os/wave) — safe to import unconditionally, no
heavy deps, no lazy-import gymnastics needed here.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("preppilot.audio.tts_cache")

CACHE_DIR = Path("./data/tts_cache")


def _cache_key(voice: str, text: str) -> str:
    normalized = text.strip()
    return hashlib.sha1(f"{voice}|{normalized}".encode("utf-8")).hexdigest()


def _cache_path(voice: str, text: str) -> Path:
    return CACHE_DIR / f"{_cache_key(voice, text)}.wav"


def get_cached_wav(voice: str, text: str) -> Optional[bytes]:
    path = _cache_path(voice, text)
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        logger.debug("TTS cache read failed for %s: %s", path, exc)
        return None


def store_wav(voice: str, text: str, wav: bytes) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(voice, text).write_bytes(wav)
    except OSError as exc:
        logger.debug("TTS cache write failed: %s", exc)


def synth_cached(synthesizer: Any, voice: str, text: str) -> Optional[bytes]:
    """Cache-through wrapper around Synthesizer.synth(text, voice).

    The voice is passed through to synth() so the cache key and the produced
    audio always agree — each voice builds its own cache set, and switching
    back to a previously-used voice is an instant cache hit."""
    cached = get_cached_wav(voice, text)
    if cached is not None:
        return cached
    wav = synthesizer.synth(text, voice=voice)
    if wav:
        store_wav(voice, text, wav)
    return wav
