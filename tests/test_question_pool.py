"""Tests for QuestionPool and its orchestrator integration — the "instant
next question" latency fix. Zero heavy deps: FakeProvider + in-memory SQLite.
"""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import Settings
from backend.db import repositories
from backend.db.models import Base
from backend.orchestrator import InterviewOrchestrator
from backend.providers.fake_provider import FakeProvider
from backend.question_pool import QuestionPool
from backend.schemas import GeneratedQuestion, SessionCreateRequest


class CountingProvider(FakeProvider):
    """Wraps FakeProvider, recording the schema title of every complete() call."""

    def __init__(self, weak: bool = False) -> None:
        super().__init__()
        self.call_titles: list[str] = []
        self._weak = weak

    def complete(self, system, messages, *, json_schema=None, temperature=0.4, think=None):
        self.call_titles.append((json_schema or {}).get("title", ""))
        return super().complete(system, messages, json_schema=json_schema, temperature=temperature, think=think)

    def _feedback(self) -> dict:  # instance override so weak-answer tests can force it
        fb = FakeProvider._feedback()
        if self._weak:
            fb["scores"] = {**fb["scores"], "overall": 3}
        return fb

    def complete_json(self, system, messages, *, schema_model, temperature=0.4, think=None):
        # FakeProvider._feedback is a staticmethod referenced directly by complete();
        # route FeedbackResult calls through the instance override instead.
        if schema_model.__name__ == "FeedbackResult":
            self.call_titles.append("FeedbackResult")
            return schema_model.model_validate(self._feedback())
        return super().complete_json(
            system, messages, schema_model=schema_model, temperature=temperature, think=think
        )


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


def make_session_row(db, role="Backend Engineer"):
    req = SessionCreateRequest(role=role, seniority="mid", focus_areas=["behavioral"])
    return repositories.create_session(db, req, provider="fake", model="canned-v1")


def seed_bank(db, role, seniority, jd_text, n, prefix="Q"):
    jd_hash = hashlib.sha256((jd_text or "").encode("utf-8")).hexdigest()
    qs = [
        GeneratedQuestion(category="behavioral", text=f"{prefix}{i}?", targets_competency="ownership")
        for i in range(n)
    ]
    return repositories.save_bank_items(db, role, seniority, jd_hash, qs)


class TestPoolBuildFromCache:
    def test_no_llm_call_when_bank_already_stocked(self, db, settings):
        session_row = make_session_row(db)
        seed_bank(db, session_row.role, session_row.seniority, "", n=settings.session.max_questions + 2)
        provider = CountingProvider()
        pool = QuestionPool(provider, db, settings, session_row)
        pool.build()
        assert pool.remaining() >= settings.session.max_questions
        assert "QuestionBankResult" not in provider.call_titles


class TestPoolFocusFilter:
    def test_only_focus_category_questions_are_served(self, db, settings):
        role = "Backend Engineer"
        # Session focuses on behavioral ONLY.
        req = SessionCreateRequest(role=role, seniority="mid", focus_areas=["behavioral"])
        session_row = repositories.create_session(db, req, provider="fake", model="canned-v1")
        jd_hash = hashlib.sha256(b"").hexdigest()
        # Bank has a mix of categories cached from earlier sessions.
        repositories.save_bank_items(db, role, "mid", jd_hash, [
            GeneratedQuestion(category="behavioral", text="Behavioral one?"),
            GeneratedQuestion(category="behavioral", text="Behavioral two?"),
            GeneratedQuestion(category="behavioral", text="Behavioral three?"),
            GeneratedQuestion(category="behavioral", text="Behavioral four?"),
            GeneratedQuestion(category="behavioral", text="Behavioral five?"),
            GeneratedQuestion(category="system_design", text="Design a system?"),
            GeneratedQuestion(category="technical_concept", text="What is a hash map?"),
        ])
        pool = QuestionPool(CountingProvider(), db, settings, session_row, mode="adaptive")
        pool.build()
        cats = {item.category for item in pool._queue}
        assert cats == {"behavioral"}, f"non-behavioral leaked in: {cats}"


class TestPoolExcludesRecentTexts:
    def test_recent_session_question_excluded(self, db, settings):
        role = "Backend Engineer"
        old_session = make_session_row(db, role=role)
        from backend.schemas import InterviewerTurn
        repositories.add_question(
            db, old_session.id, InterviewerTurn(question="Repeat Me?", category="behavioral"), order_idx=0
        )
        new_session = make_session_row(db, role=role)
        seed_bank(db, role, new_session.seniority, "", n=settings.session.max_questions + 2, prefix="Fresh")
        # Also seed a duplicate of the recent question into the bank.
        jd_hash = hashlib.sha256(b"").hexdigest()
        repositories.save_bank_items(
            db, role, new_session.seniority, jd_hash,
            [GeneratedQuestion(category="behavioral", text="Repeat Me?", targets_competency="x")],
        )
        pool = QuestionPool(CountingProvider(), db, settings, new_session, mode="adaptive")
        pool.build()
        texts = [item.text.lower() for item in pool._queue]
        assert "repeat me?" not in texts


class TestDrillSeedOrder:
    def test_seeded_ids_pop_in_order(self, db, settings):
        session_row = make_session_row(db)
        rows = seed_bank(db, session_row.role, session_row.seniority, "", n=4, prefix="Item")
        # Request them in a deliberately shuffled order.
        seed_ids = [rows[2].id, rows[0].id, rows[3].id]
        pool = QuestionPool(
            CountingProvider(), db, settings, session_row, seed_bank_ids=seed_ids, mode="drill"
        )
        pool.build()
        popped_texts = [pool.pop().question for _ in range(3)]
        assert popped_texts == [rows[2].text, rows[0].text, rows[3].text]
        assert pool.pop() is None


class TestAdvanceLlmUsage:
    @pytest.mark.asyncio
    async def test_strong_answer_advance_has_no_interviewer_turn_call(self, db, settings):
        session_row = make_session_row(db)
        seed_bank(db, session_row.role, session_row.seniority, "", n=settings.session.max_questions + 2)
        provider = CountingProvider(weak=False)
        orch = InterviewOrchestrator(provider, db, settings, session_row)
        await orch.start()
        await orch.score_answer("A solid, complete answer.", metrics=None)
        await orch.advance()
        assert "InterviewerTurn" not in provider.call_titles

    @pytest.mark.asyncio
    async def test_weak_answer_advance_triggers_interviewer_turn_call(self, db, settings):
        session_row = make_session_row(db)
        seed_bank(db, session_row.role, session_row.seniority, "", n=settings.session.max_questions + 2)
        provider = CountingProvider(weak=True)
        orch = InterviewOrchestrator(provider, db, settings, session_row)
        await orch.start()
        await orch.score_answer("A weak answer.", metrics=None)
        await orch.advance()
        assert "InterviewerTurn" in provider.call_titles


class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_reasks_same_question_and_does_not_consume_a_slot(self, db, settings):
        settings.session.max_questions = 2
        session_row = make_session_row(db)
        seed_bank(db, session_row.role, session_row.seniority, "", n=4)
        orch = InterviewOrchestrator(CountingProvider(), db, settings, session_row)
        q1 = await orch.start()

        r1 = await orch.score_answer("first attempt", metrics=None, keep_open=True)
        assert r1["done"] is False
        assert len(orch.asked_questions) == 1

        # Retry re-opens the SAME question and marks a pending replace.
        retry_turn = orch.retry_current()
        assert retry_turn.question == q1.question
        assert orch._retry_pending is True

        # The retry attempt replaces the prior one — count stays at 1, not 2.
        r2 = await orch.score_answer("second attempt", metrics=None, keep_open=True)
        assert len(orch.asked_questions) == 1
        assert r2["done"] is False
        # Report only sees the latest attempt for this question.
        assert orch.per_question_results[-1]["transcript"] == "second attempt"

        # Now advancing reaches Q2, which completes the (max=2) session.
        await orch.advance()
        r3 = await orch.score_answer("q2 answer", metrics=None, keep_open=True)
        assert r3["done"] is True
        assert len(orch.asked_questions) == 2


class TestRephrase:
    @pytest.mark.asyncio
    async def test_rephrase_reasks_reworded_without_consuming_a_slot(self, db, settings):
        settings.session.max_questions = 2
        session_row = make_session_row(db)
        seed_bank(db, session_row.role, session_row.seniority, "", n=4)

        class RewordProvider(CountingProvider):
            def complete(self, system, messages, *, json_schema=None, temperature=0.4, think=None):
                # Plain-text call (no schema) → the rephrase prompt.
                if json_schema is None:
                    return "A reworded version of the same question?"
                return super().complete(
                    system, messages, json_schema=json_schema, temperature=temperature, think=think
                )

        orch = InterviewOrchestrator(RewordProvider(), db, settings, session_row)
        q1 = await orch.start()
        await orch.score_answer("first", metrics=None, keep_open=True)
        assert len(orch.asked_questions) == 1

        turn = await orch.rephrase_current()
        assert turn.question == "A reworded version of the same question?"
        assert turn.question != q1.question
        assert orch.current_question_row.text == turn.question
        assert orch._retry_pending is True

        # Answering the reworded variation replaces the prior attempt (flat count).
        r = await orch.score_answer("second", metrics=None, keep_open=True)
        assert len(orch.asked_questions) == 1
        assert r["done"] is False


class TestDrillModeMaxQuestions:
    @pytest.mark.asyncio
    async def test_drill_max_questions_matches_seed_count(self, db, settings):
        session_row = make_session_row(db)
        rows = seed_bank(db, session_row.role, session_row.seniority, "", n=2, prefix="D")
        orch = InterviewOrchestrator(
            CountingProvider(), db, settings, session_row,
            seed_bank_ids=[r.id for r in rows], mode="drill",
        )
        assert orch.max_questions == 2

    @pytest.mark.asyncio
    async def test_ws_question_message_reports_drill_count_not_client_guess(self, db, settings):
        """Regression: the client sends its own numQuestions guess (e.g. 6)
        at session-create time, but Drill mode's true count is len(bank_ids).
        The "question" WS message must carry the server-authoritative count
        so the UI doesn't show "Q1 of 6" for a 2-question drill (it silently
        stopped at 2, which read as "drill is broken" even though the
        question SEQUENCE was always correct)."""
        from backend.main import _WSSession

        class DummyWS:
            def __init__(self) -> None:
                self.sent: list[dict] = []

            async def send_json(self, payload: dict) -> None:
                self.sent.append(payload)

        session_row = make_session_row(db)
        rows = seed_bank(db, session_row.role, session_row.seniority, "", n=2, prefix="D")
        # Simulate the client having requested 6 (its default guess), as the
        # real /api/sessions handler would receive, while bank_ids pins it to 2.
        settings.session.max_questions = 6
        orch = InterviewOrchestrator(
            CountingProvider(), db, settings, session_row,
            seed_bank_ids=[r.id for r in rows], mode="drill",
        )
        turn = await orch.start()
        ws = DummyWS()
        state = _WSSession(ws, orch)
        await state.send_question(turn)

        question_msgs = [m for m in ws.sent if m.get("type") == "question"]
        assert len(question_msgs) == 1
        assert question_msgs[0]["max_questions"] == 2
