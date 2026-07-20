"""Voice activity / end-of-turn detection.

Primary backend: silero-vad (>=5.1 pip package) speech-probability per
512-sample chunk at 16 kHz. If silero (or torch) is unavailable, an
energy-based fallback with an adaptive noise floor is used — it needs only
the stdlib (numpy is used opportunistically when installed).

All heavy imports are lazy; import of this module never raises.
"""
from __future__ import annotations

import array
import logging
import math
from typing import Any, Optional

logger = logging.getLogger("preppilot.audio")

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
CHUNK_SAMPLES = 512  # silero's required chunk size at 16 kHz (32 ms)
CHUNK_BYTES = CHUNK_SAMPLES * BYTES_PER_SAMPLE
CHUNK_MS = CHUNK_SAMPLES * 1000.0 / SAMPLE_RATE

# Keep ~300 ms of padding around the detected speech when trimming.
PAD_MS = 300.0
PAD_CHUNKS = math.ceil(PAD_MS / CHUNK_MS)

SILERO_SPEECH_PROB = 0.5     # probability threshold for "speech" per chunk
MIN_SPEECH_RUN = 3           # consecutive speech chunks (~96 ms) to open a turn
MAX_BUFFER_MS = 5 * 60 * 1000.0   # drop oldest audio past 5 min to cap memory if auto_end is off

_warned: set[str] = set()


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg)


try:  # numpy is a light optional accelerator for the energy path
    import numpy as _np
except Exception:  # pragma: no cover - numpy present in most envs
    _np = None


def _chunk_rms(chunk: bytes) -> float:
    """RMS of a PCM16 little-endian chunk, in raw sample units."""
    if _np is not None:
        samples = _np.frombuffer(chunk, dtype=_np.int16).astype(_np.float64)
        if samples.size == 0:
            return 0.0
        return float(_np.sqrt(_np.mean(samples * samples)))
    samples = array.array("h")
    samples.frombytes(chunk)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class _EnergyVAD:
    """RMS threshold with an adaptive noise floor. Stdlib-only."""

    MIN_THRESHOLD = 300.0     # absolute floor (PCM16 units) so near-digital
    FLOOR_INIT_CAP = 500.0    # silence never trips detection
    FLOOR_ALPHA = 0.9         # EMA weight for the noise floor
    FLOOR_RATIO = 3.5         # speech = rms > noise_floor * ratio

    def __init__(self) -> None:
        self._noise_floor: Optional[float] = None

    def is_speech(self, chunk: bytes) -> bool:
        rms = _chunk_rms(chunk)
        if self._noise_floor is None:
            # Cap the initial floor so an utterance starting on frame 0
            # does not poison the estimate.
            self._noise_floor = min(rms, self.FLOOR_INIT_CAP)
        threshold = max(self.MIN_THRESHOLD, self._noise_floor * self.FLOOR_RATIO)
        speech = rms > threshold
        if not speech:
            self._noise_floor = (
                self.FLOOR_ALPHA * self._noise_floor + (1.0 - self.FLOOR_ALPHA) * rms
            )
        return speech

    def reset(self) -> None:
        self._noise_floor = None


class _SileroVAD:
    """Thin wrapper around the silero-vad pip package (lazy torch import)."""

    def __init__(self) -> None:
        from silero_vad import load_silero_vad  # noqa: PLC0415 (lazy)
        import torch  # noqa: F401, PLC0415 (lazy)

        self._torch = torch
        self._model = load_silero_vad()

    def is_speech(self, chunk: bytes) -> bool:
        if _np is not None:
            audio = _np.frombuffer(chunk, dtype=_np.int16).astype(_np.float32) / 32768.0
            tensor = self._torch.from_numpy(audio)
        else:  # pragma: no cover
            samples = array.array("h")
            samples.frombytes(chunk)
            tensor = self._torch.tensor([s / 32768.0 for s in samples])
        prob = self._model(tensor, SAMPLE_RATE).item()
        return prob >= SILERO_SPEECH_PROB

    def reset(self) -> None:
        try:
            self._model.reset_states()
        except Exception:  # pragma: no cover
            pass


class TurnDetector:
    """Streaming end-of-turn detector over PCM16 mono 16 kHz frames.

    feed() accumulates audio; once speech has started and trailing silence
    reaches ``vad.end_of_turn_silence_ms``, it returns the full utterance
    (silence trimmed to ~300 ms on each side) and resets for the next turn —
    but only when ``auto_end`` is True. With ``auto_end`` False (the manual
    practice tab, to stop cutting the user off mid-thought), feed() never
    auto-completes; only flush(force=True) (the user's Done click) ends the
    turn, returning whatever's buffered so far.
    """

    def __init__(self, settings: Any, force_fallback: bool = False, auto_end: bool = True) -> None:
        vad_cfg = settings.vad
        self.backend: str = vad_cfg.backend
        self.end_of_turn_silence_ms: int = vad_cfg.end_of_turn_silence_ms
        self.chunk_ms: int = vad_cfg.chunk_ms  # expected inbound frame size (informational)
        self.auto_end: bool = auto_end

        self._vad: Any
        if self.backend == "silero" and not force_fallback:
            try:
                self._vad = _SileroVAD()
            except Exception as exc:
                _warn_once(
                    "silero",
                    f"silero-vad unavailable ({exc.__class__.__name__}: {exc}); "
                    "falling back to energy-based VAD",
                )
                self._vad = _EnergyVAD()
        else:
            if self.backend not in ("silero", "none"):
                _warn_once("vad-backend", f"Unknown VAD backend '{self.backend}'; using energy fallback")
            self._vad = _EnergyVAD()

        self._pending = b""
        self._chunks: list[tuple[bytes, bool]] = []
        self._speech_started = False
        self._speech_run = 0
        self._trailing_silence_ms = 0.0

    # ------------------------------------------------------------------ api

    def feed(self, frame: bytes) -> Optional[bytes]:
        """Feed a PCM16 frame; returns the finished utterance or None."""
        if not frame:
            return None
        self._pending += frame
        utterance: Optional[bytes] = None
        while len(self._pending) >= CHUNK_BYTES:
            chunk, self._pending = self._pending[:CHUNK_BYTES], self._pending[CHUNK_BYTES:]
            done = self._process_chunk(chunk)
            if done is not None and utterance is None:
                utterance = done
        return utterance

    def flush(self, force: bool = False) -> Optional[bytes]:
        """Return the buffered utterance, then reset.

        ``force=True`` (the user pressed "done") returns ALL buffered audio
        even when the VAD never crossed its speech threshold — otherwise a
        quiet mic or an accent near the threshold produces nothing at all
        when the user clearly did answer. Auto end-of-turn (``force=False``)
        still requires detected speech so silence isn't transcribed.
        """
        # Run whatever partial chunk remains through the detector as-is.
        if self._pending:
            leftover = self._pending
            self._pending = b""
            if len(leftover) >= CHUNK_BYTES // 2:
                self._chunks.append((leftover, False))
        if self._speech_started:
            utterance = self._assemble()
        elif force and self._chunks:
            # No speech detected but the user insists — hand the raw buffer
            # to STT, which has its own vad_filter and will return "" if it's
            # truly empty (the empty-transcript guard then asks for a retry).
            utterance = b"".join(chunk for chunk, _ in self._chunks)
        else:
            utterance = None
        self.reset()
        return utterance

    def reset(self) -> None:
        self._pending = b""
        self._chunks = []
        self._speech_started = False
        self._speech_run = 0
        self._trailing_silence_ms = 0.0
        try:
            self._vad.reset()
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------- internals

    def _process_chunk(self, chunk: bytes) -> Optional[bytes]:
        try:
            speech = self._vad.is_speech(chunk)
        except Exception as exc:
            _warn_once(
                "vad-runtime",
                f"VAD inference failed ({exc.__class__.__name__}: {exc}); "
                "switching to energy fallback",
            )
            self._vad = _EnergyVAD()
            speech = self._vad.is_speech(chunk)

        self._chunks.append((chunk, speech))
        max_chunks = int(MAX_BUFFER_MS / CHUNK_MS)
        if len(self._chunks) > max_chunks:
            # Runaway buffer (auto_end off and the user never clicks Done) —
            # drop the oldest audio rather than growing unbounded.
            self._chunks = self._chunks[-max_chunks:]
        if speech:
            self._speech_run += 1
            if self._speech_run >= MIN_SPEECH_RUN:
                self._speech_started = True
            if self._speech_started:
                self._trailing_silence_ms = 0.0
        else:
            self._speech_run = 0
            if self._speech_started:
                self._trailing_silence_ms += CHUNK_MS
                if self.auto_end and self._trailing_silence_ms >= self.end_of_turn_silence_ms:
                    utterance = self._assemble()
                    self.reset()
                    return utterance
        return None

    def _assemble(self) -> Optional[bytes]:
        speech_idx = [i for i, (_, s) in enumerate(self._chunks) if s]
        if not speech_idx:
            return None
        start = max(0, speech_idx[0] - PAD_CHUNKS)
        end = min(len(self._chunks), speech_idx[-1] + 1 + PAD_CHUNKS)
        return b"".join(chunk for chunk, _ in self._chunks[start:end])


def get_turn_detector(settings: Any, auto_end: bool = True) -> TurnDetector:
    """Fresh detector per call — one per WebSocket connection."""
    return TurnDetector(settings, auto_end=auto_end)
