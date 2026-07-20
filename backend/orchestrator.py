"""Interview turn state machine — provider- and transport-agnostic."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session as OrmSession

from backend.config import Settings
from backend.db import models, repositories
from backend.prompts.coaching import build_coaching
from backend.prompts.interviewer import build_interviewer_turn
from backend.prompts.report import build_report
from backend.providers.base import LLMProvider
from backend.question_pool import QuestionPool
from backend.schemas import DeliveryMetrics, FeedbackResult, InterviewerTurn, ReportResult

logger = logging.getLogger("preppilot.orchestrator")


class InterviewOrchestrator:
    """Drives one interview session: question -> answer -> feedback -> next."""

    def __init__(
        self,
        provider: LLMProvider,
        db_session: OrmSession,
        settings: Settings,
        session_row: models.Session,
        seed_bank_ids: list[int] | None = None,
        mode: str = "adaptive",
    ) -> None:
        self.provider = provider
        self.db = db_session
        self.settings = settings
        self.session_row = session_row
        self.mode = mode
        self.max_questions = (
            len(seed_bank_ids) if mode == "drill" and seed_bank_ids else settings.session.max_questions
        )
        self._started_at = time.monotonic()
        # In-memory turn state
        self.current_question_row: models.Question | None = None
        self.asked_questions: list[dict] = []  # [{text, category, overall_score}]
        self.per_question_results: list[dict] = []  # for the report prompt
        self._last_answered_question_row: models.Question | None = None
        # Set by retry_current(): the next score_answer replaces the prior
        # attempt at the same question instead of counting a new one, so a
        # practice-mode retry doesn't consume a question slot.
        self._retry_pending = False
        self.pool = QuestionPool(
            provider, db_session, settings, session_row, seed_bank_ids=seed_bank_ids, mode=mode
        )
        self._pool_built = False

    @property
    def _session_meta(self) -> dict:
        try:
            focus_areas = json.loads(self.session_row.focus_areas)
        except (json.JSONDecodeError, TypeError):
            focus_areas = []
        return {
            "role": self.session_row.role,
            "seniority": self.session_row.seniority,
            "jd_text": self.session_row.jd_text,
            "focus_areas": focus_areas,
            "persona": self.session_row.persona,
        }

    async def _next_turn(self, last_answer_summary: dict | None) -> InterviewerTurn:
        system, messages = build_interviewer_turn(
            self._session_meta, self.asked_questions, last_answer_summary
        )
        turn = await asyncio.to_thread(
            self.provider.complete_json,
            system,
            messages,
            schema_model=InterviewerTurn,
            temperature=self.settings.llm.temperature,
            think=False,  # templated question generation — the reasoning trace is discarded anyway
        )
        assert isinstance(turn, InterviewerTurn)
        return turn

    async def _ensure_pool_built(self) -> None:
        if not self._pool_built:
            await asyncio.to_thread(self.pool.build)
            self._pool_built = True

    async def start(self) -> InterviewerTurn:
        """Ask (and persist) the opening question."""
        await self._ensure_pool_built()
        turn = self.pool.pop() or await self._next_turn(None)
        self.current_question_row = repositories.add_question(
            self.db, self.session_row.id, turn, order_idx=0
        )
        return turn

    async def score_answer(
        self,
        transcript: str,
        metrics: Optional[DeliveryMetrics],
        audio_path: str | None = None,
        keep_open: bool = False,
    ) -> dict:
        """Persist the answer and run coaching. Does NOT generate the next question.

        Split from question-generation (see `advance()`) so the caller can send
        feedback back to the client immediately, instead of making the client
        wait through two sequential LLM calls before seeing anything.

        `keep_open`: leave current_question_row set even when the session is
        done (practice/manual-advance mode, so a retry of the final question
        still works — the caller finalizes via finish() on the user's cue).

        Returns {feedback, question_id, done}.
        """
        if self.current_question_row is None:
            raise RuntimeError("score_answer called before start()/resume()")
        question_row = self.current_question_row
        # A retry replaces the prior attempt at this same question in the
        # in-memory accounting, so it doesn't inflate the count or the report.
        replace_last = self._retry_pending
        self._retry_pending = False
        if replace_last:
            if self.asked_questions:
                self.asked_questions.pop()
            if self.per_question_results:
                self.per_question_results.pop()

        answer_row = repositories.add_answer(
            self.db, question_row.id, transcript, audio_path=audio_path
        )
        if metrics is not None:
            repositories.add_metrics(self.db, answer_row.id, metrics)

        system, messages = build_coaching(
            question=question_row.text,
            category=question_row.category,
            role=self.session_row.role,
            seniority=self.session_row.seniority,
            transcript=transcript,
            delivery_metrics=metrics,
        )
        feedback = await asyncio.to_thread(
            self.provider.complete_json,
            system,
            messages,
            schema_model=FeedbackResult,
            temperature=self.settings.llm.temperature,
        )
        assert isinstance(feedback, FeedbackResult)
        repositories.add_score_and_feedback(self.db, answer_row.id, feedback)

        self.asked_questions.append(
            {
                "text": question_row.text,
                "category": question_row.category,
                "overall_score": feedback.scores.overall,
            }
        )
        self.per_question_results.append(
            {
                "question": question_row.text,
                "category": question_row.category,
                "is_followup": question_row.is_followup,
                "transcript": transcript,
                "scores": feedback.scores.model_dump(),
                "star_completeness": feedback.star_completeness.model_dump(),
                "coaching_summary": feedback.coaching_summary,
                "delivery_metrics": metrics.model_dump() if metrics is not None else None,
            }
        )
        self._last_answered_question_row = question_row

        question_count = len(self.asked_questions)
        done = question_count >= self.max_questions
        if done:
            logger.info(
                "Session %s reached max_questions=%s — done.",
                self.session_row.id, self.max_questions,
            )
            if not keep_open:
                self.current_question_row = None
        return {"feedback": feedback, "question_id": question_row.id, "done": done}

    def retry_current(self) -> InterviewerTurn:
        """Re-open the just-answered question for another attempt (practice
        mode "Try again"). The next score_answer replaces the prior attempt in
        the accounting, so retries don't consume a question slot or double up
        in the report."""
        if self.current_question_row is None:
            raise RuntimeError("retry_current called with no open question")
        self._retry_pending = True
        row = self.current_question_row
        return InterviewerTurn(
            question=row.text,
            category=row.category,  # type: ignore[arg-type]
            is_followup=row.is_followup,
            targets_competency=row.targets_competency,
        )

    async def rephrase_current(self) -> InterviewerTurn:
        """Re-ask the current question in DIFFERENT words — same competency and
        difficulty ("Ask differently"). Persists the reworded phrasing as the
        open question (so coaching scores what was actually asked) but keeps it
        in the same slot: like retry, the next answer replaces the prior
        attempt and no question slot is consumed. Practice for the same
        question phrased multiple ways."""
        if self.current_question_row is None:
            raise RuntimeError("rephrase_current called with no open question")
        from backend.prompts.rephrase import build_rephrase
        from backend.providers.base import strip_think

        src = self.current_question_row
        system, messages = build_rephrase(
            src.text, self.session_row.role, self.session_row.seniority, src.category
        )
        raw = await asyncio.to_thread(
            self.provider.complete, system, messages, temperature=0.8, think=False
        )
        reworded = strip_think(raw).strip().strip('"').strip()
        if not reworded:
            reworded = src.text  # fall back to the original wording
        turn = InterviewerTurn(
            question=reworded,
            category=src.category,  # type: ignore[arg-type]
            is_followup=False,
            targets_competency=src.targets_competency,
        )
        # Same slot: reuse the current order_idx and mark a pending replace so
        # this variation doesn't count as an extra question.
        order_idx = src.order_idx
        self._retry_pending = True
        self.current_question_row = repositories.add_question(
            self.db, self.session_row.id, turn, order_idx=order_idx
        )
        return turn

    async def advance(self) -> InterviewerTurn:
        """Generate and persist the next question.

        Only valid immediately after `score_answer()` returned done=False (or
        from `resume()` when every persisted question is already scored).

        Drill mode always pulls the next seeded question (no follow-ups — the
        set is fixed). Adaptive/Full mode: a weak answer gets an LLM-generated
        targeted follow-up; a solid answer pops the next pre-generated pool
        question (zero LLM call — this is most of the pool's speed win).
        """
        last = self.per_question_results[-1]
        threshold = self.settings.session.followup_score_threshold
        await self._ensure_pool_built()

        next_turn: InterviewerTurn | None = None
        if self.mode != "drill" and last["scores"]["overall"] < threshold:
            last_answer_summary = {
                "question": last["question"],
                "category": last["category"],
                "scores": last["scores"],
                "star_completeness": last["star_completeness"],
                "feedback_digest": last["coaching_summary"],
                "followup_guidance": (
                    f"The session follow-up threshold is {threshold}: an overall score below "
                    f"{threshold} usually warrants a targeted follow-up on the weakest element."
                ),
            }
            next_turn = await self._next_turn(last_answer_summary)
        else:
            next_turn = self.pool.pop()
            if next_turn is None:
                last_answer_summary = {
                    "question": last["question"],
                    "category": last["category"],
                    "scores": last["scores"],
                    "star_completeness": last["star_completeness"],
                    "feedback_digest": last["coaching_summary"],
                    "followup_guidance": "",
                }
                next_turn = await self._next_turn(last_answer_summary)

        question_count = len(self.asked_questions)
        parent_id = (
            self._last_answered_question_row.id
            if next_turn.is_followup and self._last_answered_question_row is not None
            else None
        )
        self.current_question_row = repositories.add_question(
            self.db,
            self.session_row.id,
            next_turn,
            order_idx=question_count,
            parent_question_id=parent_id,
        )
        return next_turn

    async def resume(self) -> tuple[InterviewerTurn | None, bool]:
        """Rebuild in-memory state from the DB after a reconnect to an in-progress session.

        Returns (turn, is_done):
          - (turn, False): `turn` is the question the client should be shown —
            either the previously-open (unscored) question, or a freshly
            generated one if every persisted question is already scored.
          - (None, False): no questions persisted yet — caller should call start().
          - (None, True): max_questions already reached (possibly the last
            question was scored right before the disconnect) — caller should
            finish() / re-send the stored report.

        Note: `_started_at` is not restored from the DB, so the eventual
        report's duration_sec undercounts time spent before the reconnect.
        Acceptable for now (see CLAUDE.md known limitations).
        """
        resume_state = repositories.get_resume_state(self.db, self.session_row.id)
        answered = resume_state["answered"]
        open_question = resume_state["open_question"]

        self.asked_questions = []
        self.per_question_results = []
        self._last_answered_question_row = None
        for q, transcript, feedback, metrics in answered:
            if feedback is None:
                continue
            self.asked_questions.append(
                {
                    "text": q.text,
                    "category": q.category,
                    "overall_score": feedback.scores.overall,
                }
            )
            self.per_question_results.append(
                {
                    "question": q.text,
                    "category": q.category,
                    "is_followup": q.is_followup,
                    "transcript": transcript,
                    "scores": feedback.scores.model_dump(),
                    "star_completeness": feedback.star_completeness.model_dump(),
                    "coaching_summary": feedback.coaching_summary,
                    "delivery_metrics": metrics.model_dump() if metrics is not None else None,
                }
            )
            self._last_answered_question_row = q

        if open_question is not None:
            self.current_question_row = open_question
            return (
                InterviewerTurn(
                    question=open_question.text,
                    category=open_question.category,
                    is_followup=open_question.is_followup,
                    targets_competency=open_question.targets_competency,
                ),
                False,
            )

        question_count = len(self.asked_questions)
        if question_count == 0:
            return None, False
        if question_count >= self.max_questions:
            self.current_question_row = None
            return None, True

        next_turn = await self.advance()
        return next_turn, False

    async def finish(self) -> ReportResult:
        """Generate/persist the session report and mark the session completed."""
        history = repositories.get_history_aggregates(
            self.db, exclude_session_id=self.session_row.id
        )
        system, messages = build_report(
            self._session_meta, self.per_question_results, history or None
        )
        report = await asyncio.to_thread(
            self.provider.complete_json,
            system,
            messages,
            schema_model=ReportResult,
            temperature=self.settings.llm.temperature,
        )
        assert isinstance(report, ReportResult)
        # The LLM writes good prose but is unreliable at arithmetic — it would
        # report overall 0.0 / WPM 0 / confidence 0 even after a strong answer.
        # Override the NUMERIC fields with values computed from the real
        # per-answer scores and metrics; keep the LLM's qualitative text.
        self._apply_computed_scores(report)
        repositories.save_report(self.db, self.session_row.id, report)
        duration = time.monotonic() - self._started_at
        repositories.set_session_completed(
            self.db, self.session_row.id, report.overall_score, duration
        )
        return report

    def _apply_computed_scores(self, report: ReportResult) -> None:
        """Recompute overall_score, category_scores and the delivery summary
        numbers deterministically from per_question_results, so they always
        match the per-answer feedback the candidate actually saw."""
        results = self.per_question_results
        if not results:
            return

        overalls = [
            r["scores"]["overall"]
            for r in results
            if r.get("scores") and r["scores"].get("overall") is not None
        ]
        if overalls:
            report.overall_score = round(sum(overalls) / len(overalls), 1)

        by_cat: dict[str, list[float]] = {}
        for r in results:
            ov = (r.get("scores") or {}).get("overall")
            if ov is not None:
                by_cat.setdefault(r["category"], []).append(ov)
        if by_cat:
            report.category_scores = {
                cat: round(sum(v) / len(v), 1) for cat, v in by_cat.items()
            }

        metrics = [r["delivery_metrics"] for r in results if r.get("delivery_metrics")]
        if metrics:
            def _avg(key: str, only_positive: bool = False) -> float:
                vals = [m.get(key, 0) or 0 for m in metrics]
                if only_positive:
                    vals = [v for v in vals if v > 0]
                return round(sum(vals) / len(vals), 2) if vals else 0.0

            report.delivery_summary.avg_wpm = _avg("wpm", only_positive=True)
            report.delivery_summary.avg_filler_rate = _avg("filler_rate")
            report.delivery_summary.avg_confidence = _avg("confidence_proxy", only_positive=True)
