"""PrepPilot FastAPI app — REST + WebSocket transport."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import random
import threading
import time
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from backend.config import PROJECT_ROOT, get_settings
from backend.db import repositories
from backend.db.session import SessionLocal, get_db, init_db
from backend.orchestrator import InterviewOrchestrator
from backend.providers.base import ProviderError
from backend.providers.factory import get_provider
from backend.schemas import (
    DeliveryMetrics,
    InterviewerTurn,
    QuestionBankResult,
    SessionCreateRequest,
    SessionDetail,
    SessionSummary,
    StatsResult,
    TrendPoint,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("preppilot.main")

FRONTEND_DIR = PROJECT_ROOT / "frontend" / "out"  # Next.js static export (npm run build)
AUDIO_DATA_DIR = Path("./data/audio")

# Curated Kokoro voices for the settings drawer — ordered best-first (Kokoro's
# own quality grades). Descriptions are what the user sees on the voice card.
KOKORO_VOICES = [
    {"id": "af_heart", "label": "Heart", "description": "Warm American female — most natural (recommended)"},
    {"id": "af_bella", "label": "Bella", "description": "Bright, energetic American female"},
    {"id": "af_nicole", "label": "Nicole", "description": "Soft-spoken American female"},
    {"id": "af_sarah", "label": "Sarah", "description": "Calm, even American female"},
    {"id": "bf_emma", "label": "Emma", "description": "British female"},
    {"id": "am_michael", "label": "Michael", "description": "Friendly American male"},
    {"id": "bm_george", "label": "George", "description": "British male"},
    {"id": "am_adam", "label": "Adam", "description": "Deep American male"},
]

# Spoken by the voice-preview button so the user can compare voices before
# picking one. Constant text -> cached per voice, replays are instant.
VOICE_PREVIEW_TEXT = "Hi, I'm your interviewer. Tell me about a recent project you're proud of."


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    # Apply persisted runtime settings (settings drawer) over the config-file
    # values — config.yaml is the cold-start default, the DB wins after that.
    try:
        from backend.db.session import SessionLocal

        with SessionLocal() as db:
            saved_voice = repositories.get_app_setting(db, "tts_voice")
        if saved_voice and saved_voice in {v["id"] for v in KOKORO_VOICES}:
            settings.tts.voice = saved_voice
    except Exception as exc:
        logger.warning("Could not load persisted settings (using config defaults): %s", exc)
    app.state.settings = settings
    app.state.provider = get_provider(settings)
    # Per-session max_questions overrides (not persisted on the Session row)
    app.state.session_overrides = {}
    if settings.stt.preload and settings.stt.backend == "faster-whisper":
        try:
            from backend.audio.stt import get_transcriber

            threading.Thread(
                target=lambda: get_transcriber(settings).warm(),
                daemon=True, name="stt-preload",
            ).start()
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.info("STT preload skipped: %s", exc)
    logger.info(
        "PrepPilot up — provider=%s model=%s",
        app.state.provider.name, app.state.provider.model,
    )
    yield


app = FastAPI(title="PrepPilot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _serve_page(filename: str) -> FileResponse:
    path = FRONTEND_DIR / filename
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"{filename} not found — build the frontend first: cd frontend && npm install && npm run build",
        )
    return FileResponse(str(path))


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return _serve_page("index.html")


# Explicit routes for each statically-exported page so the no-trailing-slash
# URL (e.g. /interview) resolves; the StaticFiles(html=True) mount at the
# bottom handles the /interview/ trailing-slash form and _next/* assets. Any
# new exported page needs an entry here (see CLAUDE.md).
_PAGES = {
    "/dashboard": "dashboard/index.html",
    "/interview": "interview/index.html",
    "/question-bank": "question-bank/index.html",
    "/full-interview": "full-interview/index.html",
}


def _make_page_route(filename: str):
    async def route() -> FileResponse:
        return _serve_page(filename)

    return route


for _path, _file in _PAGES.items():
    app.get(_path, include_in_schema=False)(_make_page_route(_file))


# ---------------------------------------------------------------- REST


@app.post("/api/sessions", response_model=SessionSummary)
async def create_session(
    req: SessionCreateRequest, db: OrmSession = Depends(get_db)
) -> SessionSummary:
    provider = app.state.provider
    row = repositories.create_session(db, req, provider.name, provider.model)
    # Drill mode's question count is authoritative from bank_ids (the exact
    # set the user chose to repeat) — the client always sends max_questions
    # too (SetupForm defaults it to 6), so it must not clobber that here.
    max_questions_override = None if (req.mode == "drill" and req.bank_ids) else req.max_questions
    if max_questions_override is not None or req.bank_ids:
        app.state.session_overrides[row.id] = {
            "max_questions": max_questions_override,
            "bank_ids": req.bank_ids,
        }
    return SessionSummary(
        id=row.id,
        created_at=row.created_at,
        role=row.role,
        seniority=row.seniority,
        status=row.status,
        mode=row.mode,
        overall_score=row.overall_score,
        question_count=0,
        duration_sec=row.duration_sec,
        provider=row.provider,
        model=row.model,
    )


@app.get("/api/sessions", response_model=list[SessionSummary])
async def get_sessions(db: OrmSession = Depends(get_db)) -> list[SessionSummary]:
    return repositories.list_sessions(db)


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session_detail(
    session_id: int, db: OrmSession = Depends(get_db)
) -> SessionDetail:
    detail = repositories.get_session_detail(db, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int, db: OrmSession = Depends(get_db)) -> dict:
    if not repositories.delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}


@app.delete("/api/sessions")
async def delete_all_sessions(db: OrmSession = Depends(get_db)) -> dict:
    count = repositories.delete_all_sessions(db)
    return {"status": "deleted", "count": count}


@app.get("/api/trends", response_model=list[TrendPoint])
async def get_trends(db: OrmSession = Depends(get_db)) -> list[TrendPoint]:
    return repositories.get_trends(db)


@app.get("/api/stats", response_model=StatsResult)
async def get_stats(db: OrmSession = Depends(get_db)) -> StatsResult:
    return repositories.get_stats(db)


class QuestionBankRequest(BaseModel):
    role: str = "Software Engineer"
    seniority: str = "mid"
    jd_text: str = ""
    n_behavioral: int = 4
    n_system_design: int = 2
    n_technical: int = 3


@app.post("/api/question-bank", response_model=QuestionBankResult)
async def generate_question_bank(
    req: QuestionBankRequest, db: OrmSession = Depends(get_db)
) -> QuestionBankResult:
    from backend.prompts.question_gen import build_question_gen

    settings = app.state.settings
    system, messages = build_question_gen(
        req.role,
        req.seniority,
        req.jd_text,
        n_behavioral=req.n_behavioral,
        n_system_design=req.n_system_design,
        n_technical=req.n_technical,
    )
    try:
        result = await asyncio.to_thread(
            app.state.provider.complete_json,
            system,
            messages,
            schema_model=QuestionBankResult,
            temperature=settings.llm.temperature,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    jd_hash = hashlib.sha256(req.jd_text.encode("utf-8")).hexdigest()
    saved_rows = repositories.save_bank_items(db, req.role, req.seniority, jd_hash, result.questions)
    for question, row in zip(result.questions, saved_rows):
        question.id = row.id
    return result


class AdoptQuestionRequest(BaseModel):
    """Persist a single question the candidate already answered (from a
    report or session detail) into the bank, so it can be Drilled later."""
    text: str
    category: str = "behavioral"
    role: str = "Software Engineer"
    seniority: str = "mid"
    targets_competency: str = ""


@app.post("/api/question-bank/adopt")
async def adopt_question(
    req: AdoptQuestionRequest, db: OrmSession = Depends(get_db)
) -> dict:
    from backend.schemas import GeneratedQuestion as _GeneratedQuestion

    q = _GeneratedQuestion(
        category=req.category,  # type: ignore[arg-type]
        text=req.text,
        targets_competency=req.targets_competency,
    )
    jd_hash = hashlib.sha256(b"").hexdigest()  # adopted questions have no JD context
    rows = repositories.save_bank_items(db, req.role, req.seniority, jd_hash, [q])
    return {"id": rows[0].id}


class SettingsUpdateRequest(BaseModel):
    tts_voice: str


@app.get("/api/settings")
async def get_app_settings() -> dict:
    """Current runtime settings + the voice catalog for the settings drawer."""
    settings = app.state.settings
    return {
        "tts_voice": settings.tts.voice,
        "tts_backend": settings.tts.backend,
        "voices": KOKORO_VOICES,
    }


@app.put("/api/settings")
async def update_app_settings(
    req: SettingsUpdateRequest, db: OrmSession = Depends(get_db)
) -> dict:
    """Apply + persist a settings change. Takes effect immediately for every
    session (in-flight ones included — they read settings.tts.voice per synth
    call), and survives restarts via the app_settings table."""
    if req.tts_voice not in {v["id"] for v in KOKORO_VOICES}:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {req.tts_voice!r}")
    repositories.set_app_setting(db, "tts_voice", req.tts_voice)
    app.state.settings.tts.voice = req.tts_voice
    return {"tts_voice": req.tts_voice}


class VoicePreviewRequest(BaseModel):
    voice: str


@app.post("/api/settings/voice-preview")
async def voice_preview(req: VoicePreviewRequest) -> dict:
    """Synthesize the sample line in the requested voice so the user can
    listen before choosing. {"audio_b64": null} when TTS isn't loaded in this
    process — the drawer shows a note instead of a broken play button."""
    if req.voice not in {v["id"] for v in KOKORO_VOICES}:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {req.voice!r}")
    try:
        from backend.audio.tts import get_synthesizer
        from backend.audio.tts_cache import synth_cached

        synth = get_synthesizer(app.state.settings)
        wav = await asyncio.to_thread(synth_cached, synth, req.voice, VOICE_PREVIEW_TEXT)
    except Exception as exc:
        logger.info("Voice preview unavailable: %s", exc)
        wav = None
    return {"audio_b64": base64.b64encode(wav).decode("ascii") if wav else None}


# The classic HR/screening set every real interview opens or closes with.
# {company} is replaced with the user's target company ("this company" when
# blank). Kept as behavioral — STAR coaching still applies to these.
HR_QUESTION_TEMPLATES: list[tuple[str, str]] = [
    ("Tell me about yourself.", "self_introduction"),
    ("What are your salary expectations for this role?", "compensation_negotiation"),
    ("Why do you want to leave your current company?", "motivation"),
    ("Why do you want to work at {company}?", "company_motivation"),
    ("What do you know about {company} and our products?", "company_research"),
    ("Where do you see yourself in five years?", "career_goals"),
    ("What is your greatest strength, and what is one weakness you are working on?", "self_awareness"),
]


class HrSetRequest(BaseModel):
    company: str = ""
    role: str = "Software Engineer"
    seniority: str = "mid"


@app.post("/api/question-bank/hr-set", response_model=QuestionBankResult)
async def add_hr_question_set(
    req: HrSetRequest, db: OrmSession = Depends(get_db)
) -> QuestionBankResult:
    """Add the common HR/screening questions to the bank, personalized with
    the target company name. Idempotent — re-adding returns the same rows."""
    from backend.schemas import GeneratedQuestion as _GeneratedQuestion

    company = req.company.strip() or "this company"
    questions = [
        _GeneratedQuestion(
            category="behavioral",
            text=template.format(company=company),
            targets_competency=competency,
            difficulty="easy",
        )
        for template, competency in HR_QUESTION_TEMPLATES
    ]
    jd_hash = hashlib.sha256(b"hr-set").hexdigest()
    rows = repositories.save_bank_items(db, req.role, req.seniority, jd_hash, questions)
    for question, row in zip(questions, rows):
        question.id = row.id
    return QuestionBankResult(questions=questions)


@app.get("/api/question-bank/items")
async def list_bank_questions(db: OrmSession = Depends(get_db)) -> dict:
    """Everything in the bank (newest first) — feeds the Drill question
    picker on the interview setup page."""
    rows = repositories.list_bank_items(db)
    return {
        "items": [
            {
                "id": r.id,
                "text": r.text,
                "category": r.category,
                "difficulty": r.difficulty,
                "role": r.role,
                "seniority": r.seniority,
                "targets_competency": r.targets_competency,
            }
            for r in rows
        ]
    }


@app.get("/api/question-bank/random")
async def random_bank_question(db: OrmSession = Depends(get_db)) -> dict:
    """Home's "question of the day" — a random pick from whatever the
    candidate has already generated into the bank. {"question": null} if the
    bank is empty (nothing generated yet)."""
    row = repositories.get_random_bank_item(db)
    if row is None:
        return {"question": None}
    return {
        "question": {
            "id": row.id,
            "text": row.text,
            "category": row.category,
            "targets_competency": row.targets_competency,
            "difficulty": row.difficulty,
            "role": row.role,
            "seniority": row.seniority,
        }
    }


def _module_available(name: str) -> bool:
    """Cheap importability probe — does NOT import or load the module/model."""
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def build_health_flags(settings, provider_name: str) -> tuple[list[str], dict]:
    """Pure, unit-testable core of /api/health.

    Returns (degraded_messages, flags). `flags` is machine-readable so the
    frontend can gate UI (disable voice mode, show a demo-mode banner)
    without string-matching `degraded`.

    Distinguishes "backend disabled by config" (normal, e.g. stt.backend:
    none) from "backend configured but the package isn't importable in this
    process" (the mistake that silently breaks voice mode when launched with
    the wrong Python — see run.ps1/run.bat).
    """
    degraded: list[str] = []

    demo_llm = provider_name == "fake" and settings.llm.provider != "fake"
    if demo_llm:
        degraded.append(
            f"llm: DEMO MODE — canned responses (Ollama unreachable at "
            f"{settings.llm.base_url}); scores/feedback are not real"
        )
    elif provider_name != settings.llm.provider:
        degraded.append(
            f"llm: configured '{settings.llm.provider}' unavailable, using '{provider_name}'"
        )

    stt_missing = settings.stt.backend == "faster-whisper" and not _module_available(
        "faster_whisper"
    )
    if stt_missing:
        degraded.append(
            "stt: configured 'faster-whisper' but package missing — launch with .venv (see run.ps1)"
        )
    elif settings.stt.backend == "none":
        degraded.append("stt: disabled (text mode only)")

    vad_missing = settings.vad.backend == "silero" and not (
        _module_available("silero_vad") and _module_available("torch")
    )
    if vad_missing:
        degraded.append(
            "vad: configured 'silero' but package missing — launch with .venv (see run.ps1)"
        )

    tts_missing = settings.tts.backend == "kokoro" and not _module_available("kokoro")
    if tts_missing:
        degraded.append(
            "tts: configured 'kokoro' but package missing — launch with .venv (see run.ps1)"
        )
    elif settings.tts.backend == "none":
        degraded.append("tts: disabled")

    flags = {
        "demo_llm": demo_llm,
        "stt_missing": stt_missing,
        "vad_missing": vad_missing,
        "tts_missing": tts_missing,
    }
    return degraded, flags


@app.get("/api/health")
async def health() -> dict:
    settings = app.state.settings
    provider = app.state.provider
    degraded, flags = build_health_flags(settings, provider.name)
    return {
        "status": "ok",
        "llm_provider": provider.name,
        "llm_model": provider.model,
        "stt_backend": settings.stt.backend,
        "tts_backend": settings.tts.backend,
        "degraded": degraded,
        "flags": flags,
    }


# ---------------------------------------------------------------- WebSocket


def _save_utterance_wav(session_id: int, order_idx: int, pcm16: bytes) -> str | None:
    try:
        out_dir = AUDIO_DATA_DIR / str(session_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"utterance_{order_idx:03d}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm16)
        return str(path)
    except OSError as exc:
        logger.warning("Failed to save utterance WAV: %s", exc)
        return None


# Process-wide guard so concurrent sessions prewarming the same pooled
# question don't both pay the synth cost — first one in wins, the rest see
# a cache hit from tts_cache once it lands.
_tts_prewarm_inflight: set[str] = set()
_tts_prewarm_lock = threading.Lock()

# Pings Ollama with a throwaway request on WS connect so qwen3 is already
# loaded into VRAM by the time the user finishes reading the first question,
# instead of the first real (coaching) call paying that load cost. Throttled
# so a burst of connects doesn't spam Ollama with warm pings.
_ollama_warm_lock = threading.Lock()
_ollama_last_warm_ts = 0.0
OLLAMA_WARM_COOLDOWN_SEC = 60.0


def _maybe_warm_ollama(provider) -> None:
    global _ollama_last_warm_ts
    if getattr(provider, "name", "") != "ollama":
        return
    now = time.monotonic()
    with _ollama_warm_lock:
        if now - _ollama_last_warm_ts < OLLAMA_WARM_COOLDOWN_SEC:
            return
        _ollama_last_warm_ts = now

    def _worker() -> None:
        try:
            provider.complete(
                "You are a helper.", [{"role": "user", "content": "ok"}],
                temperature=0.0, think=False,
            )
        except Exception as exc:  # pragma: no cover - best-effort only
            logger.debug("Ollama warm-up ping failed (non-fatal): %s", exc)

    threading.Thread(target=_worker, daemon=True, name="ollama-warm").start()

# Spoken immediately after the user finishes answering (Full Interview mode's
# "natural" back-and-forth) — short so the cache-cold first synth is cheap,
# and cached forever after via tts_cache since the text never changes.
ACK_PHRASES = [
    "Thanks, let me take a look.",
    "Got it, one moment.",
    "Okay, noted.",
]

# In-memory cache for "show a strong answer" — keyed by question_id, process-
# wide (same question text -> same model answer, no need to persist it).
_model_answer_cache: dict[int, str] = {}


class _WSSession:
    """Per-connection state and helpers for the interview WebSocket."""

    def __init__(self, ws: WebSocket, orchestrator: InterviewOrchestrator) -> None:
        self.ws = ws
        self.orchestrator = orchestrator
        self.settings = orchestrator.settings
        self.question_idx = 0  # order_idx of the current question
        self.done = False
        self._turn_detector = None
        self._turn_detector_failed = False
        self._synthesizer = None
        self._synthesizer_failed = False
        # Turn-detector options, settable via the "set_options" message before
        # (or after) the detector is created. Practice tab sends auto_end_turn
        # =false on connect (fixes cutting the user off); Full Interview sends
        # true with a longer patience window.
        self._auto_end_turn = True
        self._end_of_turn_silence_ms: int | None = None
        # Manual advance (practice tab): after feedback, wait for the user to
        # click "Try again" or "Next question" instead of auto-advancing. Lets
        # the candidate re-answer a question. Full Interview leaves this off
        # for a hands-free, always-forward flow.
        self._manual_advance = False
        self._awaiting_complete = False  # last scored answer was the final one

    def set_options(
        self,
        auto_end_turn: bool,
        end_of_turn_silence_ms: int | None = None,
        manual_advance: bool | None = None,
    ) -> None:
        self._auto_end_turn = auto_end_turn
        if manual_advance is not None:
            self._manual_advance = manual_advance
        if end_of_turn_silence_ms is not None:
            self._end_of_turn_silence_ms = max(500, min(10000, end_of_turn_silence_ms))
        if self._turn_detector is not None:
            self._turn_detector.auto_end = self._auto_end_turn
            if self._end_of_turn_silence_ms is not None:
                self._turn_detector.end_of_turn_silence_ms = self._end_of_turn_silence_ms

    async def send(self, payload: dict) -> None:
        await self.ws.send_json(payload)

    async def send_status(self, state: str, detail: str | None = None) -> None:
        msg: dict = {"type": "status", "state": state}
        if detail:
            msg["detail"] = detail
        await self.send(msg)

    def _get_synthesizer(self):
        if self._synthesizer is None and not self._synthesizer_failed:
            try:
                from backend.audio.tts import get_synthesizer

                self._synthesizer = get_synthesizer(self.settings)
            except (ImportError, RuntimeError, AttributeError) as exc:
                logger.info("TTS unavailable, questions will be text-only: %s", exc)
                self._synthesizer_failed = True
        return self._synthesizer

    def _get_turn_detector(self):
        if self._turn_detector is None and not self._turn_detector_failed:
            try:
                from backend.audio.vad import get_turn_detector

                self._turn_detector = get_turn_detector(self.settings, auto_end=self._auto_end_turn)
                if self._end_of_turn_silence_ms is not None:
                    self._turn_detector.end_of_turn_silence_ms = self._end_of_turn_silence_ms
            except (ImportError, RuntimeError, AttributeError) as exc:
                logger.warning("VAD unavailable, audio mode disabled: %s", exc)
                self._turn_detector_failed = True
        return self._turn_detector

    async def _question_audio_b64(self, text: str) -> str | None:
        synth = self._get_synthesizer()
        if synth is None:
            return None
        try:
            from backend.audio.tts_cache import synth_cached

            wav = await asyncio.to_thread(synth_cached, synth, self.settings.tts.voice, text)
            return base64.b64encode(wav).decode("ascii") if wav else None
        except Exception as exc:
            logger.warning("TTS synth failed: %s", exc)
            self._synthesizer_failed = True
            return None

    async def _ack_audio_b64(self) -> str | None:
        """A short spoken acknowledgment played the instant the user finishes
        answering (before scoring), so Full Interview mode's turn-taking
        feels responsive instead of going silent for the scoring LLM call."""
        synth = self._get_synthesizer()
        if synth is None:
            return None
        try:
            from backend.audio.tts_cache import synth_cached

            phrase = random.choice(ACK_PHRASES)
            wav = await asyncio.to_thread(synth_cached, synth, self.settings.tts.voice, phrase)
            return base64.b64encode(wav).decode("ascii") if wav else None
        except Exception as exc:
            logger.debug("Ack synth failed (non-fatal): %s", exc)
            return None

    def prewarm_pool_audio(self) -> None:
        """Fire-and-forget: synthesize+cache every pooled question's audio in
        a background thread, so by the time the pool naturally advances to
        them, playback is a cache hit instead of a multi-second Kokoro call.
        Never blocks the WS loop and never raises."""
        synth = self._get_synthesizer()
        if synth is None:
            return
        voice = self.settings.tts.voice
        texts = self.orchestrator.pool.peek_texts()
        if not texts:
            return

        def _worker() -> None:
            from backend.audio.tts_cache import get_cached_wav, synth_cached

            for text in texts:
                with _tts_prewarm_lock:
                    if text in _tts_prewarm_inflight or get_cached_wav(voice, text) is not None:
                        continue
                    _tts_prewarm_inflight.add(text)
                try:
                    synth_cached(synth, voice, text)
                except Exception as exc:  # pragma: no cover - best-effort only
                    logger.debug("TTS prewarm failed for one question: %s", exc)
                finally:
                    _tts_prewarm_inflight.discard(text)

        threading.Thread(target=_worker, daemon=True, name="tts-prewarm").start()

    async def send_question(self, turn: InterviewerTurn) -> None:
        msg = {
            "type": "question",
            "text": turn.question,
            "category": turn.category,
            "is_followup": turn.is_followup,
            "order_idx": self.question_idx,
            # Server-authoritative total — the client's guess at session-create
            # time (from its numQuestions field) is NOT reliable for Drill mode,
            # where the true count is len(bank_ids) and overrides it (see
            # create_session's max_questions_override). Without this, Drill
            # sessions showed "Q1 of 6" while actually stopping at 2.
            "max_questions": self.orchestrator.max_questions,
        }
        audio_b64 = await self._question_audio_b64(turn.question)
        if audio_b64:
            msg["audio_b64"] = audio_b64
        await self.send(msg)

    async def submit(
        self,
        transcript: str,
        metrics: Optional[DeliveryMetrics],
        audio_path: str | None = None,
    ) -> None:
        await self.send_status("thinking", detail="scoring your answer")
        result = await self.orchestrator.score_answer(
            transcript, metrics, audio_path=audio_path, keep_open=self._manual_advance
        )
        feedback = result["feedback"]
        feedback_msg: dict = {
            "type": "feedback",
            "question_id": result["question_id"],
            **feedback.model_dump(),
        }
        # Drill mode's payoff: show how this attempt compares to the last
        # time the candidate answered the same question, if ever.
        question_text = repositories.get_question_text(self.orchestrator.db, result["question_id"])
        if question_text:
            previous_attempt = await asyncio.to_thread(
                repositories.get_previous_attempt,
                self.orchestrator.db, question_text, self.orchestrator.session_row.id,
            )
            if previous_attempt is not None:
                feedback_msg["previous_attempt"] = previous_attempt
        await self.send(feedback_msg)

        # Manual advance (practice tab): stop after feedback and let the user
        # choose to retry the same question or move on. The auto flow (Full
        # Interview, and any client that doesn't opt in) advances immediately.
        if self._manual_advance:
            self._awaiting_complete = result["done"]
            await self.send({"type": "await_action", "session_complete": result["done"]})
            return

        if result["done"]:
            await self.finish()
            return
        await self._advance_and_send()

    async def _advance_and_send(self) -> None:
        await self.send_status("thinking", detail="preparing next question")
        try:
            next_turn = await self.orchestrator.advance()
        except ProviderError:
            # The user already has their feedback and can't act on this failure
            # themselves (there's nothing to resubmit) — one silent retry before
            # surfacing an error is worth the extra ~30s.
            logger.warning(
                "advance() failed once for session %s; retrying",
                self.orchestrator.session_row.id,
            )
            next_turn = await self.orchestrator.advance()
        self.question_idx += 1
        await self.send_question(next_turn)
        await self.send_status("listening")

    async def next_question(self) -> None:
        """Manual-advance client asked to move on (practice tab). Ends the
        session if that was the last question, else advances."""
        if self._awaiting_complete:
            await self.finish()
            return
        await self._advance_and_send()

    async def retry_question(self) -> None:
        """Manual-advance client asked to re-answer the current question."""
        try:
            turn = self.orchestrator.retry_current()
        except RuntimeError:
            return
        self._awaiting_complete = False
        await self.send_question(turn)
        await self.send_status("listening")

    async def rephrase_question(self) -> None:
        """Manual-advance client asked to re-ask the current question in
        different words (an LLM call, so surface a thinking status first)."""
        await self.send_status("thinking", detail="rephrasing the question")
        try:
            turn = await self.orchestrator.rephrase_current()
        except RuntimeError:
            return
        except ProviderError:
            try:
                turn = await self.orchestrator.rephrase_current()
            except (RuntimeError, ProviderError):
                # Rewording failed — fall back to the exact-same-question retry
                # so the button still does something useful.
                try:
                    turn = self.orchestrator.retry_current()
                except RuntimeError:
                    return
        self._awaiting_complete = False
        await self.send_question(turn)
        await self.send_status("listening")

    async def finish(self) -> None:
        if self.done:
            return
        self.done = True
        await self.send_status("thinking", detail="generating report")
        report = await self.orchestrator.finish()
        await self.send({"type": "report", **report.model_dump()})
        await self.send_status("done")

    async def send_model_answer(self, question_id: int) -> None:
        """"Show a strong answer" — a cached, on-demand exemplary answer for
        one question. Never blocks turn-taking; failures are silent (the
        button just doesn't produce text)."""
        cached = _model_answer_cache.get(question_id)
        if cached is not None:
            await self.send({"type": "model_answer", "question_id": question_id, "text": cached})
            return
        row = await asyncio.to_thread(repositories.get_question, self.orchestrator.db, question_id)
        if row is None:
            return
        # Prefer rewriting the candidate's own answer ("how I'd say it") over a
        # generic ideal — far more useful. Falls back to generic if unanswered.
        transcript = await asyncio.to_thread(
            repositories.get_answer_transcript, self.orchestrator.db, question_id
        )
        try:
            from backend.prompts.model_answer import build_model_answer
            from backend.providers.base import strip_think

            system, messages = build_model_answer(
                row.text, self.orchestrator.session_row.role,
                self.orchestrator.session_row.seniority, row.category,
                candidate_answer=transcript,
            )
            raw = await asyncio.to_thread(
                self.orchestrator.provider.complete, system, messages, temperature=0.5, think=False,
            )
            text = strip_think(raw)
        except Exception as exc:
            logger.warning("Model-answer generation failed for question %s: %s", question_id, exc)
            return
        _model_answer_cache[question_id] = text
        await self.send({"type": "model_answer", "question_id": question_id, "text": text})

    async def handle_text_answer(self, text: str) -> None:
        metrics: Optional[DeliveryMetrics] = None
        try:
            from backend.analytics.metrics import compute_text_metrics

            metrics = await asyncio.to_thread(compute_text_metrics, text)
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.info("Text metrics unavailable: %s", exc)
        if metrics is not None:
            # Send metrics before submit() so the client can show instant
            # rule-based alerts (fillers, short-answer) while the LLM scores.
            await self.send({"type": "metrics", **metrics.model_dump()})
        await self.submit(text, metrics)

    async def handle_utterance(self, pcm16: bytes) -> None:
        if not pcm16:
            return
        await self.send_status("transcribing")
        try:
            from backend.audio.stt import get_transcriber

            transcriber = get_transcriber(self.settings)
            transcription = await asyncio.to_thread(
                transcriber.transcribe, pcm16, 16000
            )
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.warning("STT unavailable: %s", exc)
            await self.send(
                {"type": "error", "message": "Transcription unavailable — please answer in text mode."}
            )
            return
        if not transcription.text.strip():
            # Don't submit/score a blank answer — happens with silence, a
            # muted mic, or (previously, before health-flag surfacing) a
            # missing STT backend. Let the user retry the same question
            # instead of scoring "" and reporting a confusing zero-word-count
            # delivery note.
            logger.info(
                "Empty transcription for session %s q%s (%.1fs of audio)",
                self.orchestrator.session_row.id, self.question_idx, len(pcm16) / 32000.0,
            )
            await self.send(
                {
                    "type": "error",
                    "code": "empty_transcript",
                    "message": "No speech recognized — please try again.",
                }
            )
            await self.send_status("listening")
            return
        await self.send({"type": "transcript_final", "text": transcription.text})
        ack_audio = await self._ack_audio_b64()
        if ack_audio:
            await self.send({"type": "ack", "audio_b64": ack_audio})
        await self.send_status("analyzing")
        metrics: Optional[DeliveryMetrics] = None
        try:
            from backend.analytics.metrics import compute_delivery_metrics

            metrics = await asyncio.to_thread(
                compute_delivery_metrics, pcm16, 16000, transcription, self.settings
            )
            await self.send({"type": "metrics", **metrics.model_dump()})
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.warning("Delivery metrics unavailable: %s", exc)
        audio_path = await asyncio.to_thread(
            _save_utterance_wav, self.orchestrator.session_row.id, self.question_idx, pcm16
        )
        await self.submit(transcription.text, metrics, audio_path=audio_path)

    async def handle_audio_frame(self, frame: bytes) -> None:
        detector = self._get_turn_detector()
        if detector is None:
            await self.send(
                {"type": "error", "message": "Audio mode unavailable — please answer in text mode."}
            )
            return
        utterance = detector.feed(frame)
        if utterance:
            await self.handle_utterance(utterance)

    async def handle_end_turn(self) -> None:
        detector = self._get_turn_detector()
        if detector is None:
            return
        # Manual "done" — force-return the buffer even if the VAD didn't flag
        # speech (quiet mic / accent), so the answer isn't silently dropped.
        utterance = detector.flush(force=True)
        if utterance:
            await self.handle_utterance(utterance)
        else:
            await self.send(
                {
                    "type": "error",
                    "code": "empty_transcript",
                    "message": "No audio captured — check your microphone and try again.",
                }
            )
            await self.send_status("listening")


@app.websocket("/ws/session/{session_id}")
async def ws_session(ws: WebSocket, session_id: int) -> None:
    await ws.accept()
    _maybe_warm_ollama(app.state.provider)
    db = SessionLocal()
    try:
        session_row = repositories.get_session(db, session_id)
        if session_row is None:
            await ws.send_json({"type": "error", "message": f"Session {session_id} not found"})
            await ws.close(code=1008)
            return

        settings = app.state.settings
        override = app.state.session_overrides.get(session_id) or {}
        orchestrator = InterviewOrchestrator(
            app.state.provider,
            db,
            settings,
            session_row,
            seed_bank_ids=override.get("bank_ids"),
            mode=session_row.mode,
        )
        if override.get("max_questions") is not None:
            orchestrator.max_questions = override["max_questions"]
        state = _WSSession(ws, orchestrator)

        # A completed session (report already generated) just gets the report
        # replayed — nothing left to resume.
        if session_row.status == "completed":
            detail = repositories.get_session_detail(db, session_id)
            if detail is not None and detail.report is not None:
                await ws.send_json({"type": "resumed", "answered_count": len(detail.answers)})
                await ws.send_json({"type": "report", **detail.report.model_dump()})
                await state.send_status("done")
                await ws.close()
                return

        try:
            turn, is_done = await orchestrator.resume()
        except ProviderError as exc:
            logger.error("Failed to resume interview: %s", exc)
            await ws.send_json({"type": "error", "message": f"Could not resume interview: {exc}"})
            await ws.close(code=1011)
            return

        answered_count = len(orchestrator.asked_questions)
        if turn is None and not is_done:
            # Nothing persisted yet — this is a fresh connection, not a reconnect.
            try:
                turn = await orchestrator.start()
            except ProviderError as exc:
                logger.error("Failed to start interview: %s", exc)
                await ws.send_json({"type": "error", "message": f"Could not start interview: {exc}"})
                await ws.close(code=1011)
                return
            state.question_idx = 0
            await state.send_question(turn)
            await state.send_status("listening")
        elif turn is not None:
            if answered_count:
                await ws.send_json({"type": "resumed", "answered_count": answered_count})
            state.question_idx = orchestrator.current_question_row.order_idx
            await state.send_question(turn)
            await state.send_status("listening")
        else:
            # is_done: every question is scored (possibly right up to the
            # disconnect) but the report was never generated — finish it now.
            if answered_count:
                await ws.send_json({"type": "resumed", "answered_count": answered_count})
            await state.finish()

        if not state.done:
            state.prewarm_pool_audio()

        while not state.done:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                logger.info("WS disconnected for session %s", session_id)
                return
            try:
                if message.get("bytes") is not None:
                    await state.handle_audio_frame(message["bytes"])
                    continue
                text = message.get("text")
                if text is None:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    await state.send({"type": "error", "message": "Invalid JSON message"})
                    continue
                msg_type = payload.get("type", "")
                if msg_type == "answer_text":
                    await state.handle_text_answer(payload.get("text", ""))
                elif msg_type == "end_turn":
                    await state.handle_end_turn()
                elif msg_type == "end_session":
                    await state.finish()
                elif msg_type == "set_options":
                    state.set_options(
                        bool(payload.get("auto_end_turn", True)),
                        payload.get("end_of_turn_silence_ms"),
                        manual_advance=payload.get("manual_advance"),
                    )
                elif msg_type == "next_question":
                    await state.next_question()
                elif msg_type == "retry_question":
                    await state.retry_question()
                elif msg_type == "rephrase_question":
                    await state.rephrase_question()
                elif msg_type == "model_answer":
                    qid = payload.get("question_id")
                    if isinstance(qid, int):
                        await state.send_model_answer(qid)
                else:
                    await state.send(
                        {"type": "error", "message": f"Unknown message type: {msg_type!r}"}
                    )
            except WebSocketDisconnect:
                raise
            except ProviderError as exc:
                logger.error("Provider error in session %s: %s", session_id, exc)
                await state.send({"type": "error", "message": f"LLM error: {exc}"})
                if orchestrator.current_question_row is not None:
                    # score_answer only clears current_question_row on success,
                    # so if it's still set the user can safely resubmit the
                    # same answer — unlock the UI instead of leaving it stuck
                    # behind the error toast.
                    await state.send_status(
                        "listening",
                        detail="Something went wrong scoring that answer — please resubmit.",
                    )
            except Exception as exc:
                logger.exception("Error handling WS message in session %s", session_id)
                await state.send({"type": "error", "message": f"Internal error: {exc}"})

        await ws.close()
    except WebSocketDisconnect:
        logger.info("WS disconnected for session %s", session_id)
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    _settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=_settings.server.host,
        port=_settings.server.port,
        # Defaults (20s/20s) are too tight for a 30-60s local LLM turn — the
        # event loop can miss a pong under GIL contention from STT/prosody
        # work and uvicorn kills the socket with 1011. Same flags apply when
        # launching via `python -m uvicorn ...` (see CLAUDE.md).
        ws_ping_interval=25.0,
        ws_ping_timeout=60.0,
    )


# Static assets from the Next.js export — registered last so /api and /ws win.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
