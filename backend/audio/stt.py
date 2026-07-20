"""Speech-to-text via faster-whisper, with graceful degradation.

faster-whisper (and CUDA) are only expected on the target machine. Here and
in text-only mode the transcriber degrades to an empty TranscriptionResult —
the orchestrator treats empty text as "no speech".
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any, Optional

from backend import schemas

logger = logging.getLogger("preppilot.audio")

_warned: set[str] = set()
_model_lock = threading.Lock()
_model: Any = None
_model_key: Optional[tuple[str, str, str]] = None
_transcriber: Optional["Transcriber"] = None
_dll_dirs_added = False


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg)


def _add_cuda_dll_dirs() -> None:
    """Put the pip-installed cuDNN/cuBLAS runtime DLLs on the loader search path.

    ctranslate2 (faster-whisper's backend) needs cuDNN 9 + cuBLAS at runtime.
    Rather than requiring a system-wide CUDA/cuDNN install, these can be
    installed as ordinary pip wheels (`nvidia-cudnn-cu12`, `nvidia-cublas-cu12`).

    Verified empirically: `os.add_dll_directory()` is NOT enough here —
    ctranslate2's own CUDA library loader (a plain `LoadLibrary` call in its
    C++ code) doesn't consult the AddDllDirectory list, only `PATH`. So this
    prepends the wheels' `bin/` dirs to `PATH` instead. No-op (and always
    safe) if the wheels aren't installed or we're not on Windows; the
    existing cuda->cpu/int8 fallback in `_get_model` still applies if CUDA
    loading fails for any reason.
    """
    global _dll_dirs_added
    if _dll_dirs_added or sys.platform != "win32":
        return
    _dll_dirs_added = True
    bin_dirs: list[str] = []
    for pkg in ("nvidia.cudnn", "nvidia.cublas"):
        try:
            import importlib

            mod = importlib.import_module(pkg)
            # These ship as PEP 420 namespace packages (no __init__.py), so
            # __file__ is None — the install location lives in __path__ instead.
            pkg_dir = mod.__file__ and os.path.dirname(mod.__file__)
            if not pkg_dir:
                paths = list(getattr(mod, "__path__", []) or [])
                pkg_dir = paths[0] if paths else None
            if not pkg_dir:
                continue
            bin_dir = os.path.join(pkg_dir, "bin")
            if os.path.isdir(bin_dir):
                bin_dirs.append(bin_dir)
        except Exception as exc:  # pragma: no cover - best-effort only
            logger.debug("Could not locate DLL directory for %s: %s", pkg, exc)
    if bin_dirs:
        os.environ["PATH"] = os.pathsep.join(bin_dirs) + os.pathsep + os.environ.get("PATH", "")
        logger.debug("Prepended CUDA DLL directories to PATH: %s", bin_dirs)


def _get_model(model_name: str, device: str, compute_type: str) -> Any:
    """Load the WhisperModel once at module level; None if unavailable.

    device "auto" tries CUDA first, then CPU with int8.
    """
    global _model, _model_key
    key = (model_name, device, compute_type)
    with _model_lock:
        if _model is not None and _model_key == key:
            return _model
        _add_cuda_dll_dirs()
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415 (lazy)
        except Exception as exc:
            _warn_once(
                "faster-whisper",
                f"faster-whisper unavailable ({exc.__class__.__name__}: {exc}); "
                "STT disabled — returning empty transcriptions",
            )
            return None

        candidates: list[tuple[str, str]]
        if device == "auto":
            candidates = [("cuda", compute_type), ("cpu", "int8")]
        else:
            candidates = [(device, compute_type)]
            if device == "cuda":
                candidates.append(("cpu", "int8"))

        for dev, ctype in candidates:
            try:
                logger.info("Loading whisper model %s on %s (%s)", model_name, dev, ctype)
                _model = WhisperModel(model_name, device=dev, compute_type=ctype)
                _model_key = key
                return _model
            except Exception as exc:
                logger.warning("Whisper load failed on %s (%s): %s", dev, ctype, exc)
        _warn_once("whisper-load", "Could not load whisper model on any device; STT disabled")
        return None


class Transcriber:
    """Transcribes PCM16 mono audio to text with word timestamps."""

    def __init__(self, settings: Any) -> None:
        self._stt_cfg = settings.stt

    def warm(self) -> None:
        """Load the model now instead of on the first utterance. Call from a
        background thread at server startup — never raises (same graceful
        degradation as transcribe(): a load failure here just means the
        first real transcribe() call pays the load cost instead)."""
        if self._stt_cfg.backend != "faster-whisper":
            return
        try:
            _get_model(self._stt_cfg.model, self._stt_cfg.device, self._stt_cfg.compute_type)
        except Exception as exc:  # pragma: no cover - best-effort only
            logger.debug("STT warm-up failed (non-fatal): %s", exc)

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> schemas.TranscriptionResult:
        duration_sec = len(pcm16) / 2.0 / sample_rate if sample_rate > 0 else 0.0
        empty = schemas.TranscriptionResult(text="", words=[], duration_sec=duration_sec)

        if self._stt_cfg.backend != "faster-whisper":
            _warn_once("stt-none", f"STT backend '{self._stt_cfg.backend}' — returning empty transcription")
            return empty
        if not pcm16:
            return empty

        model = _get_model(self._stt_cfg.model, self._stt_cfg.device, self._stt_cfg.compute_type)
        if model is None:
            return empty

        try:
            import numpy as np  # noqa: PLC0415 (lazy; ships with faster-whisper)

            audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
            segments, info = model.transcribe(
                audio,
                beam_size=5,
                word_timestamps=True,
                vad_filter=True,
            )
            words: list[schemas.WordTiming] = []
            parts: list[str] = []
            for segment in segments:
                parts.append(segment.text.strip())
                for w in segment.words or []:
                    words.append(
                        schemas.WordTiming(word=w.word.strip(), start=float(w.start), end=float(w.end))
                    )
            return schemas.TranscriptionResult(
                text=" ".join(p for p in parts if p).strip(),
                words=words,
                language=getattr(info, "language", "en") or "en",
                duration_sec=float(getattr(info, "duration", 0.0) or duration_sec),
            )
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            return empty


def get_transcriber(settings: Any) -> Transcriber:
    """Module-level singleton (the model itself is also cached)."""
    global _transcriber
    if _transcriber is None:
        _transcriber = Transcriber(settings)
    return _transcriber
