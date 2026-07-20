"""Tests for the "show a strong answer" on-demand model-answer feature
(_WSSession.send_model_answer in backend/main.py) — a plain-text, cached,
best-effort completion requested via the model_answer WS message.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import Settings
from backend.db import repositories
from backend.db.models import Base
from backend.main import _WSSession, _model_answer_cache
from backend.orchestrator import InterviewOrchestrator
from backend.providers.fake_provider import FakeProvider
from backend.schemas import SessionCreateRequest


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


class TestModelAnswer:
    @pytest.mark.asyncio
    async def test_returns_text_for_current_question(self, db):
        state, ws = await make_started_state(db)
        qid = state.orchestrator.current_question_row.id

        await state.send_model_answer(qid)

        msgs = [m for m in ws.sent if m.get("type") == "model_answer"]
        assert len(msgs) == 1
        assert msgs[0]["question_id"] == qid
        assert msgs[0]["text"] == "This is a canned response from the fake provider."

    @pytest.mark.asyncio
    async def test_caches_across_calls(self, db):
        state, ws = await make_started_state(db)
        qid = state.orchestrator.current_question_row.id
        _model_answer_cache.pop(qid, None)

        await state.send_model_answer(qid)
        assert qid in _model_answer_cache

        # Swap the provider's complete() to blow up — a cache hit must not call it.
        def _boom(*args, **kwargs):
            raise AssertionError("should not call the provider on a cache hit")

        state.orchestrator.provider.complete = _boom
        ws.sent.clear()
        await state.send_model_answer(qid)

        msgs = [m for m in ws.sent if m.get("type") == "model_answer"]
        assert len(msgs) == 1
        assert msgs[0]["text"] == "This is a canned response from the fake provider."

    @pytest.mark.asyncio
    async def test_unknown_question_id_sends_nothing(self, db):
        state, ws = await make_started_state(db)

        await state.send_model_answer(999999)

        assert not any(m.get("type") == "model_answer" for m in ws.sent)
