"""The session report's NUMBERS (overall, category scores, delivery summary)
must be computed from real per-answer data, not taken from the LLM — which
would report 0.0 overall / WPM 0 / confidence 0 even after a strong answer
(the bug the user hit). See InterviewOrchestrator._apply_computed_scores.
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
from backend.schemas import ReportResult, SessionCreateRequest


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


def _orch(db):
    req = SessionCreateRequest(role="SWE", seniority="mid", focus_areas=["behavioral"])
    row = repositories.create_session(db, req, provider="fake", model="canned-v1")
    return InterviewOrchestrator(FakeProvider(), db, Settings(), row)


def _result(category, overall, wpm=None, filler=None, conf=None):
    metrics = None
    if wpm is not None or conf is not None or filler is not None:
        metrics = {"wpm": wpm or 0, "filler_rate": filler or 0.0, "confidence_proxy": conf or 0}
    return {
        "question": "Q?",
        "category": category,
        "is_followup": False,
        "transcript": "an answer",
        "scores": {"overall": overall},
        "star_completeness": {},
        "coaching_summary": "",
        "delivery_metrics": metrics,
    }


class TestComputedReportScores:
    def test_overall_and_delivery_come_from_answers_not_llm(self, db):
        orch = _orch(db)
        orch.per_question_results = [
            _result("behavioral", overall=8, wpm=120, filler=0.02, conf=90),
            _result("behavioral", overall=6, wpm=140, filler=0.04, conf=70),
        ]
        # Simulate the LLM returning all-zero numbers (the reported bug).
        report = ReportResult(overall_score=0.0)
        report.delivery_summary.avg_wpm = 0
        report.delivery_summary.avg_confidence = 0

        orch._apply_computed_scores(report)

        assert report.overall_score == 7.0                 # mean(8, 6)
        assert report.category_scores["behavioral"] == 7.0
        assert report.delivery_summary.avg_wpm == 130.0    # mean(120, 140)
        assert report.delivery_summary.avg_confidence == 80.0  # mean(90, 70)
        assert report.delivery_summary.avg_filler_rate == 0.03

    def test_single_strong_answer_is_not_zero(self, db):
        orch = _orch(db)
        orch.per_question_results = [_result("behavioral", overall=9, wpm=130, conf=96)]
        report = ReportResult(overall_score=0.0)
        orch._apply_computed_scores(report)
        assert report.overall_score == 9.0

    def test_empty_results_leaves_report_untouched(self, db):
        orch = _orch(db)
        orch.per_question_results = []
        report = ReportResult(overall_score=5.5)
        orch._apply_computed_scores(report)
        assert report.overall_score == 5.5

    def test_zero_wpm_text_answers_excluded_from_wpm_average(self, db):
        orch = _orch(db)
        # One voice answer (wpm 120) + one text answer (wpm 0) → wpm avg ignores 0.
        orch.per_question_results = [
            _result("behavioral", overall=7, wpm=120, conf=88),
            _result("behavioral", overall=7, wpm=0, conf=0),
        ]
        report = ReportResult(overall_score=0.0)
        orch._apply_computed_scores(report)
        assert report.delivery_summary.avg_wpm == 120.0
        assert report.delivery_summary.avg_confidence == 88.0
