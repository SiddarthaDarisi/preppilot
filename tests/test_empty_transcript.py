"""Tests for the empty-transcript guard in _WSSession.handle_utterance
(backend/main.py). A blank transcription (silence, muted mic, or previously
a missing STT backend) must not be scored — the same question should stay
open and the client told to retry, instead of the coach reporting a
confusing "zero word count" delivery note on an answer that was never heard.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import Settings
from backend.db import repositories
from backend.db.models import Base
from backend.main import _WSSession
from backend.orchestrator import InterviewOrchestrator
from backend.providers.fake_provider import FakeProvider
from backend.schemas import SessionCreateRequest, TranscriptionResult


class DummyWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()


async def make_started_state(db) -> tuple[_WSSession, DummyWS]:
    settings = Settings()
    req = SessionCreateRequest(role="Software Engineer", seniority="mid", focus_areas=["behavioral"])
    session_row = repositories.create_session(db, req, provider="fake", model="canned-v1")
    orch = InterviewOrchestrator(FakeProvider(), db, settings, session_row)
    await orch.start()
    ws = DummyWS()
    state = _WSSession(ws, orch)
    return state, ws


class TestEmptyTranscriptGuard:
    @pytest.mark.asyncio
    async def test_blank_transcript_is_not_submitted(self, db, monkeypatch):
        state, ws = await make_started_state(db)
        question_before = state.orchestrator.current_question_row

        class BlankTranscriber:
            def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> TranscriptionResult:
                return TranscriptionResult(text="   ", words=[], duration_sec=1.0)

        monkeypatch.setattr(
            "backend.audio.stt.get_transcriber", lambda settings: BlankTranscriber()
        )

        await state.handle_utterance(b"\x00" * 32000)

        types = [m.get("type") for m in ws.sent]
        assert "transcript_final" not in types
        assert "feedback" not in types
        error_msgs = [m for m in ws.sent if m.get("type") == "error"]
        assert len(error_msgs) == 1
        assert error_msgs[0]["code"] == "empty_transcript"
        # Status ends on "listening" so the UI unlocks for a retry.
        assert ws.sent[-1] == {"type": "status", "state": "listening"}
        # The same question is still open — nothing was scored.
        assert state.orchestrator.current_question_row is question_before

    @pytest.mark.asyncio
    async def test_real_transcript_still_flows_through(self, db, monkeypatch):
        state, ws = await make_started_state(db)

        class RealTranscriber:
            def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> TranscriptionResult:
                return TranscriptionResult(text="This is a real answer.", words=[], duration_sec=1.0)

        monkeypatch.setattr(
            "backend.audio.stt.get_transcriber", lambda settings: RealTranscriber()
        )

        await state.handle_utterance(b"\x00" * 32000)

        types = [m.get("type") for m in ws.sent]
        assert "transcript_final" in types
        assert "feedback" in types
        assert not any(m.get("type") == "error" for m in ws.sent)
