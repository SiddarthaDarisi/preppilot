"""Tests for session deletion (repositories.delete_session / delete_all_sessions).
Verifies the ORM cascade removes questions/answers/metrics/scores/feedback/report.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import models, repositories
from backend.db.models import Base
from backend.schemas import (
    DeliveryMetrics,
    FeedbackResult,
    InterviewerTurn,
    ReportResult,
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


def _full_session(db):
    req = SessionCreateRequest(role="SWE", seniority="mid", focus_areas=["behavioral"])
    session_row = repositories.create_session(db, req, provider="fake", model="canned-v1")
    turn = InterviewerTurn(question="Q1", category="behavioral")
    q = repositories.add_question(db, session_row.id, turn, order_idx=0)
    answer = repositories.add_answer(db, q.id, transcript="answer")
    repositories.add_metrics(db, answer.id, DeliveryMetrics(word_count=10))
    repositories.add_score_and_feedback(
        db, answer.id, FeedbackResult.model_validate(FakeProvider._feedback())
    )
    repositories.save_report(db, session_row.id, ReportResult.model_validate(FakeProvider._report()))
    return session_row


class TestDeleteSession:
    def test_delete_one_cascades(self, db):
        s = _full_session(db)
        assert repositories.delete_session(db, s.id) is True
        # Every child table is empty afterwards.
        for model in (
            models.Session,
            models.Question,
            models.Answer,
            models.DeliveryMetricsRow,
            models.Score,
            models.Feedback,
            models.Report,
        ):
            assert db.scalar(select(func.count()).select_from(model)) == 0

    def test_delete_missing_returns_false(self, db):
        assert repositories.delete_session(db, 999) is False

    def test_delete_all(self, db):
        _full_session(db)
        _full_session(db)
        assert repositories.delete_all_sessions(db) == 2
        assert db.scalar(select(func.count()).select_from(models.Session)) == 0

    def test_delete_one_leaves_others(self, db):
        s1 = _full_session(db)
        s2 = _full_session(db)
        repositories.delete_session(db, s1.id)
        remaining = db.scalars(select(models.Session)).all()
        assert [r.id for r in remaining] == [s2.id]
