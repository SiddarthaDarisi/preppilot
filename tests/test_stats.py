"""Tests for repositories.get_stats() — the /api/stats aggregate powering the
dashboard's 'Filler habits' card. Zero heavy deps (in-memory SQLite)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import Settings
from backend.db import repositories
from backend.db.models import Base
from backend.schemas import (
    DeliveryMetrics,
    FeedbackResult,
    InterviewerTurn,
    SessionCreateRequest,
)
from backend.providers.fake_provider import FakeProvider


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


def _completed_session_with_fillers(db, filler_words: dict[str, int]):
    req = SessionCreateRequest(role="SWE", seniority="mid", focus_areas=["behavioral"])
    session_row = repositories.create_session(db, req, provider="fake", model="canned-v1")
    turn = InterviewerTurn(question="Q", category="behavioral")
    q = repositories.add_question(db, session_row.id, turn, order_idx=0)
    answer = repositories.add_answer(db, q.id, transcript="an answer")
    metrics = DeliveryMetrics(word_count=100, filler_words=filler_words, duration_sec=30.0)
    repositories.add_metrics(db, answer.id, metrics)
    repositories.add_score_and_feedback(
        db, answer.id, FeedbackResult.model_validate(FakeProvider._feedback())
    )
    repositories.set_session_completed(db, session_row.id, overall=7.0, duration=42.0)
    return session_row


def _completed_session_with_scores(
    db,
    competency: str,
    overall_score: int,
    session_overall: float = 7.0,
    confidence_proxy: float = 70.0,
    expressiveness: float = 60.0,
):
    """Builds one completed session with a single scored answer, so tests can
    control targets_competency / overall (for the heatmap) and confidence_proxy
    / expressiveness / session overall_score (for the readiness blend)."""
    req = SessionCreateRequest(role="SWE", seniority="mid", focus_areas=["behavioral"])
    session_row = repositories.create_session(db, req, provider="fake", model="canned-v1")
    turn = InterviewerTurn(question="Q", category="behavioral", targets_competency=competency)
    q = repositories.add_question(db, session_row.id, turn, order_idx=0)
    answer = repositories.add_answer(db, q.id, transcript="an answer")
    metrics = DeliveryMetrics(
        word_count=100,
        duration_sec=30.0,
        confidence_proxy=confidence_proxy,
        expressiveness=expressiveness,
    )
    repositories.add_metrics(db, answer.id, metrics)
    feedback = FeedbackResult.model_validate(FakeProvider._feedback())
    feedback.scores.overall = overall_score
    repositories.add_score_and_feedback(db, answer.id, feedback)
    repositories.set_session_completed(db, session_row.id, overall=session_overall, duration=42.0)
    return session_row


class TestGetStats:
    def test_empty_db_returns_zeros(self, db):
        stats = repositories.get_stats(db)
        assert stats.total_sessions == 0
        assert stats.total_answers == 0
        assert stats.top_fillers == []

    def test_aggregates_and_ranks_fillers(self, db):
        _completed_session_with_fillers(db, {"um": 3, "like": 1})
        _completed_session_with_fillers(db, {"um": 2, "you know": 4})

        stats = repositories.get_stats(db)
        assert stats.total_sessions == 2
        assert stats.total_answers == 2
        assert stats.total_practice_sec == pytest.approx(84.0)
        assert stats.filler_totals == {"um": 5, "like": 1, "you know": 4}
        # top_fillers sorted by count desc.
        assert stats.top_fillers[0].word == "um"
        assert stats.top_fillers[0].count == 5
        assert stats.top_fillers[1].word == "you know"

    def test_active_sessions_excluded(self, db):
        # An active (not completed) session should not contribute.
        req = SessionCreateRequest(role="SWE", seniority="mid", focus_areas=["behavioral"])
        session_row = repositories.create_session(db, req, provider="fake", model="canned-v1")
        turn = InterviewerTurn(question="Q", category="behavioral")
        q = repositories.add_question(db, session_row.id, turn, order_idx=0)
        answer = repositories.add_answer(db, q.id, transcript="x")
        repositories.add_metrics(
            db, answer.id, DeliveryMetrics(filler_words={"um": 9}, duration_sec=5.0)
        )
        stats = repositories.get_stats(db)
        assert stats.total_sessions == 0
        assert stats.filler_totals == {}

    def test_competency_heatmap_sorted_worst_first(self, db):
        _completed_session_with_scores(db, "ownership", overall_score=9)
        _completed_session_with_scores(db, "conflict_resolution", overall_score=3)
        _completed_session_with_scores(db, "communication", overall_score=6)

        stats = repositories.get_stats(db)
        names = [c.name for c in stats.competencies]
        assert names == ["conflict_resolution", "communication", "ownership"]
        assert stats.competencies[0].avg == 3.0
        assert stats.competencies[0].count == 1

    def test_readiness_score_blends_overall_confidence_expressiveness(self, db):
        # overall=8 (session-level, 0-10) -> 80 on the 0-100 scale, weight .60
        # confidence_proxy=70, weight .25; expressiveness=60, weight .15
        # 80*.60 + 70*.25 + 60*.15 = 48 + 17.5 + 9 = 74.5
        _completed_session_with_scores(
            db, "ownership", overall_score=8, session_overall=8.0,
            confidence_proxy=70.0, expressiveness=60.0,
        )
        stats = repositories.get_stats(db)
        assert stats.readiness_score == pytest.approx(74.5)

    def test_readiness_score_none_with_no_completed_sessions(self, db):
        stats = repositories.get_stats(db)
        assert stats.readiness_score is None


class TestRandomBankItem:
    def test_empty_bank_returns_none(self, db):
        assert repositories.get_random_bank_item(db) is None

    def test_returns_a_row_from_the_bank(self, db):
        from backend.schemas import GeneratedQuestion

        repositories.save_bank_items(
            db, "SWE", "mid", "hash123",
            [GeneratedQuestion(category="behavioral", text="Tell me about a time...")],
        )
        row = repositories.get_random_bank_item(db)
        assert row is not None
        assert row.text == "Tell me about a time..."
