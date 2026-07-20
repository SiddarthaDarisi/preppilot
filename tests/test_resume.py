"""Tests for InterviewOrchestrator.resume() — rebuilding in-memory turn state
from the DB after a WebSocket reconnect (see backend/main.py ws_session).

Must pass with NO heavy deps: uses the FakeProvider and an in-memory SQLite DB.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import Settings
from backend.db import repositories
from backend.db.models import Base
from backend.orchestrator import InterviewOrchestrator
from backend.providers.fake_provider import FakeProvider
from backend.schemas import FeedbackResult, InterviewerTurn, SessionCreateRequest


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


@pytest.fixture()
def settings() -> Settings:
    s = Settings()
    s.session.max_questions = 3
    s.session.followup_score_threshold = 6
    return s


def make_session_row(db):
    req = SessionCreateRequest(role="Software Engineer", seniority="mid", focus_areas=["behavioral"])
    return repositories.create_session(db, req, provider="fake", model="canned-v1")


def score_a_question(db, question_row):
    """Add an answer + score + feedback to a question, as score_answer() would."""
    answer_row = repositories.add_answer(db, question_row.id, transcript="A solid answer.")
    feedback = FeedbackResult.model_validate(FakeProvider._feedback())
    repositories.add_score_and_feedback(db, answer_row.id, feedback)
    return answer_row, feedback


class TestResumeOpenQuestion:
    @pytest.mark.asyncio
    async def test_resume_returns_unscored_question(self, db, settings):
        session_row = make_session_row(db)
        turn = InterviewerTurn(question="Tell me about yourself.", category="behavioral")
        question_row = repositories.add_question(db, session_row.id, turn, order_idx=0)

        orch = InterviewOrchestrator(FakeProvider(), db, settings, session_row)
        resumed_turn, is_done = await orch.resume()

        assert is_done is False
        assert resumed_turn is not None
        assert resumed_turn.question == "Tell me about yourself."
        assert orch.current_question_row.id == question_row.id
        assert orch.asked_questions == []


class TestResumeAdvancesWhenFullyScored:
    @pytest.mark.asyncio
    async def test_resume_generates_next_question(self, db, settings):
        session_row = make_session_row(db)
        turn = InterviewerTurn(question="Q1", category="behavioral")
        q1 = repositories.add_question(db, session_row.id, turn, order_idx=0)
        score_a_question(db, q1)

        orch = InterviewOrchestrator(FakeProvider(), db, settings, session_row)
        resumed_turn, is_done = await orch.resume()

        assert is_done is False
        assert resumed_turn is not None
        assert len(orch.asked_questions) == 1
        assert orch.asked_questions[0]["text"] == "Q1"
        # advance() persisted a new question at order_idx=1
        assert orch.current_question_row is not None
        assert orch.current_question_row.order_idx == 1
        assert orch.current_question_row.text == resumed_turn.question


class TestResumeDoneAtMax:
    @pytest.mark.asyncio
    async def test_resume_reports_done_when_max_reached(self, db, settings):
        settings.session.max_questions = 2
        session_row = make_session_row(db)
        turn1 = InterviewerTurn(question="Q1", category="behavioral")
        q1 = repositories.add_question(db, session_row.id, turn1, order_idx=0)
        score_a_question(db, q1)
        turn2 = InterviewerTurn(question="Q2", category="behavioral")
        q2 = repositories.add_question(db, session_row.id, turn2, order_idx=1)
        score_a_question(db, q2)

        orch = InterviewOrchestrator(FakeProvider(), db, settings, session_row)
        resumed_turn, is_done = await orch.resume()

        assert resumed_turn is None
        assert is_done is True
        assert orch.current_question_row is None
        assert len(orch.asked_questions) == 2


class TestResumeEmptySession:
    @pytest.mark.asyncio
    async def test_resume_on_empty_session_signals_start(self, db, settings):
        session_row = make_session_row(db)
        orch = InterviewOrchestrator(FakeProvider(), db, settings, session_row)
        resumed_turn, is_done = await orch.resume()

        assert resumed_turn is None
        assert is_done is False
        assert orch.asked_questions == []


class TestResumeRetriedAnswerPicksScoredOne:
    @pytest.mark.asyncio
    async def test_unscored_retry_answer_does_not_count_as_open(self, db, settings):
        """A ProviderError during score_answer() can leave an Answer row with no
        Score (see backend/main.py's ProviderError recovery, which lets the user
        resubmit onto the SAME question — current_question_row is untouched).
        get_resume_state must treat that question as still-open, not as scored
        with a dangling unscored answer."""
        session_row = make_session_row(db)
        turn = InterviewerTurn(question="Q1", category="behavioral")
        q1 = repositories.add_question(db, session_row.id, turn, order_idx=0)
        # Simulate a failed scoring attempt: an Answer row with no Score/Feedback.
        repositories.add_answer(db, q1.id, transcript="first attempt, LLM failed")

        state = repositories.get_resume_state(db, session_row.id)
        assert state["open_question"] is not None
        assert state["open_question"].id == q1.id
        assert state["answered"] == []
