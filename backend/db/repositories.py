"""Repository functions — all persistence goes through here."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from backend.db import models
from backend.schemas import (
    AnswerRecord,
    DeliveryMetrics,
    FeedbackResult,
    FillerStat,
    GeneratedQuestion,
    InterviewerTurn,
    ReportResult,
    SessionCreateRequest,
    SessionDetail,
    SessionSummary,
    StatsResult,
    TrendPoint,
)

logger = logging.getLogger("preppilot.db.repositories")


def create_session(
    db: OrmSession, req: SessionCreateRequest, provider: str, model: str
) -> models.Session:
    row = models.Session(
        role=req.role,
        seniority=req.seniority,
        jd_text=req.jd_text,
        focus_areas=json.dumps(req.focus_areas),
        provider=provider,
        model=model,
        mode=req.mode,
        persona=req.persona,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_session(db: OrmSession, session_id: int) -> Optional[models.Session]:
    return db.get(models.Session, session_id)


def _question_count(db: OrmSession, session_id: int) -> int:
    return db.scalar(
        select(func.count(models.Question.id)).where(models.Question.session_id == session_id)
    ) or 0


def _to_summary(db: OrmSession, row: models.Session) -> SessionSummary:
    return SessionSummary(
        id=row.id,
        created_at=row.created_at,
        role=row.role,
        seniority=row.seniority,
        status=row.status,
        mode=row.mode,
        overall_score=row.overall_score,
        question_count=_question_count(db, row.id),
        duration_sec=row.duration_sec,
        provider=row.provider,
        model=row.model,
    )


def list_sessions(db: OrmSession) -> list[SessionSummary]:
    rows = db.scalars(
        select(models.Session).order_by(models.Session.created_at.desc())
    ).all()
    return [_to_summary(db, row) for row in rows]


def add_question(
    db: OrmSession,
    session_id: int,
    turn: InterviewerTurn,
    order_idx: int,
    parent_question_id: int | None = None,
) -> models.Question:
    row = models.Question(
        session_id=session_id,
        order_idx=order_idx,
        category=turn.category,
        text=turn.question,
        is_followup=turn.is_followup,
        parent_question_id=parent_question_id,
        targets_competency=turn.targets_competency,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_answer(
    db: OrmSession,
    question_id: int,
    transcript: str,
    audio_path: str | None = None,
) -> models.Answer:
    row = models.Answer(
        question_id=question_id,
        transcript=transcript,
        audio_path=audio_path,
        ended_at=models.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_metrics(db: OrmSession, answer_id: int, metrics: DeliveryMetrics) -> models.DeliveryMetricsRow:
    row = models.DeliveryMetricsRow(
        answer_id=answer_id,
        wpm=metrics.wpm,
        pause_ratio=metrics.pause_ratio,
        long_pause_count=metrics.long_pause_count,
        filler_count=metrics.filler_count,
        filler_rate=metrics.filler_rate,
        pitch_mean=metrics.pitch_mean_hz,
        pitch_std=metrics.pitch_std_hz,
        energy_cv=metrics.energy_cv,
        confidence_proxy=metrics.confidence_proxy,
        ser_label=metrics.ser_label,
        ser_confidence=metrics.ser_confidence,
        raw_json=metrics.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_score_and_feedback(
    db: OrmSession, answer_id: int, feedback: FeedbackResult
) -> tuple[models.Score, models.Feedback]:
    score_row = models.Score(
        answer_id=answer_id,
        content_score=feedback.scores.content_relevance,
        structure_score=feedback.scores.structure,
        specificity_score=feedback.scores.specificity,
        star_completeness=feedback.star_completeness.model_dump(),
        delivery_score=feedback.scores.delivery,
        technical_accuracy=feedback.scores.technical_accuracy,
        overall=feedback.scores.overall,
    )
    feedback_row = models.Feedback(
        answer_id=answer_id,
        strengths_json=feedback.strengths,
        improvements_json=[imp.model_dump() for imp in feedback.improvements],
        coaching_text=feedback.coaching_summary,
        rubric_json=feedback.model_dump(),
    )
    db.add_all([score_row, feedback_row])
    db.commit()
    db.refresh(score_row)
    db.refresh(feedback_row)
    return score_row, feedback_row


def set_session_completed(
    db: OrmSession, session_id: int, overall: float | None, duration: float | None
) -> None:
    row = db.get(models.Session, session_id)
    if row is None:
        logger.warning("set_session_completed: session %s not found", session_id)
        return
    row.status = "completed"
    row.overall_score = overall
    row.duration_sec = duration
    db.commit()


def save_report(db: OrmSession, session_id: int, report: ReportResult) -> models.Report:
    row = models.Report(
        session_id=session_id,
        summary_json=report.model_dump(),
        practice_plan_json=[item.model_dump() for item in report.practice_plan],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_resume_state(db: OrmSession, session_id: int) -> dict:
    """Everything the orchestrator needs to rebuild in-memory state on reconnect.

    Returns {"answered": [(Question, transcript, FeedbackResult|None, DeliveryMetrics|None), ...],
             "open_question": Question|None}
    ordered by order_idx. `open_question` is the lowest-order_idx question with
    no scored answer yet — either never answered, or answered but the coaching
    call failed/never completed (see backend/schemas.py Scores clamp + the WS
    ProviderError recovery path). A retried answer can leave more than one
    Answer row per question; we pick the most recent scored one.
    """
    questions = db.scalars(
        select(models.Question)
        .where(models.Question.session_id == session_id)
        .order_by(models.Question.order_idx)
    ).all()

    answered: list[tuple] = []
    open_question: models.Question | None = None
    for q in questions:
        answer_row = db.scalars(
            select(models.Answer)
            .join(models.Score, models.Score.answer_id == models.Answer.id)
            .where(models.Answer.question_id == q.id)
            .order_by(models.Answer.id.desc())
        ).first()
        if answer_row is None:
            open_question = q
            break
        feedback = None
        if answer_row.feedback is not None and answer_row.feedback.rubric_json:
            feedback = FeedbackResult.model_validate(answer_row.feedback.rubric_json)
        metrics = None
        if answer_row.metrics is not None and answer_row.metrics.raw_json:
            metrics = DeliveryMetrics.model_validate(answer_row.metrics.raw_json)
        answered.append((q, answer_row.transcript, feedback, metrics))

    return {"answered": answered, "open_question": open_question}


def get_session_detail(db: OrmSession, session_id: int) -> Optional[SessionDetail]:
    row = db.get(models.Session, session_id)
    if row is None:
        return None
    answers: list[AnswerRecord] = []
    questions = db.scalars(
        select(models.Question)
        .where(models.Question.session_id == session_id)
        .order_by(models.Question.order_idx)
    ).all()
    for q in questions:
        if q.answer is None:
            continue
        metrics = None
        if q.answer.metrics is not None and q.answer.metrics.raw_json:
            metrics = DeliveryMetrics.model_validate(q.answer.metrics.raw_json)
        feedback = None
        if q.answer.feedback is not None and q.answer.feedback.rubric_json:
            feedback = FeedbackResult.model_validate(q.answer.feedback.rubric_json)
        answers.append(
            AnswerRecord(
                question_id=q.id,
                question=q.text,
                category=q.category,
                is_followup=q.is_followup,
                transcript=q.answer.transcript,
                metrics=metrics,
                feedback=feedback,
            )
        )
    report = None
    if row.report is not None and row.report.summary_json:
        report = ReportResult.model_validate(row.report.summary_json)
    return SessionDetail(summary=_to_summary(db, row), answers=answers, report=report)


def _session_score_rows(db: OrmSession, session_id: int) -> list[tuple[str, models.Score]]:
    """(category, Score) pairs for every scored answer in a session."""
    stmt = (
        select(models.Question.category, models.Score)
        .join(models.Answer, models.Answer.question_id == models.Question.id)
        .join(models.Score, models.Score.answer_id == models.Answer.id)
        .where(models.Question.session_id == session_id)
    )
    return [(cat, score) for cat, score in db.execute(stmt).all()]


def _category_averages(pairs: list[tuple[str, models.Score]]) -> dict[str, float]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for category, score in pairs:
        buckets[category].append(score.overall)
    return {cat: round(sum(vals) / len(vals), 2) for cat, vals in buckets.items()}


def _session_metric_averages(db: OrmSession, session_id: int) -> dict[str, float | None]:
    stmt = (
        select(
            func.avg(models.DeliveryMetricsRow.wpm),
            func.avg(models.DeliveryMetricsRow.filler_rate),
            func.avg(models.DeliveryMetricsRow.confidence_proxy),
        )
        .join(models.Answer, models.Answer.id == models.DeliveryMetricsRow.answer_id)
        .join(models.Question, models.Question.id == models.Answer.question_id)
        .where(models.Question.session_id == session_id)
    )
    wpm, filler, conf = db.execute(stmt).one()

    # expressiveness has no dedicated column (added after the table existed;
    # avoids a migration) — it only lives in raw_json, so average it in
    # Python instead of SQL.
    raw_jsons_stmt = (
        select(models.DeliveryMetricsRow.raw_json)
        .join(models.Answer, models.Answer.id == models.DeliveryMetricsRow.answer_id)
        .join(models.Question, models.Question.id == models.Answer.question_id)
        .where(models.Question.session_id == session_id)
    )
    expr_values = [
        rj.get("expressiveness")
        for (rj,) in db.execute(raw_jsons_stmt).all()
        if rj and rj.get("expressiveness")
    ]

    return {
        "avg_wpm": round(wpm, 2) if wpm is not None else None,
        "avg_filler_rate": round(filler, 4) if filler is not None else None,
        "avg_confidence": round(conf, 2) if conf is not None else None,
        "avg_expressiveness": round(sum(expr_values) / len(expr_values), 2) if expr_values else None,
    }


def get_trends(db: OrmSession) -> list[TrendPoint]:
    """One TrendPoint per completed session, oldest first."""
    rows = db.scalars(
        select(models.Session)
        .where(models.Session.status == "completed")
        .order_by(models.Session.created_at)
    ).all()
    points: list[TrendPoint] = []
    for row in rows:
        metrics = _session_metric_averages(db, row.id)
        points.append(
            TrendPoint(
                session_id=row.id,
                created_at=row.created_at,
                overall_score=row.overall_score,
                category_scores=_category_averages(_session_score_rows(db, row.id)),
                **metrics,
            )
        )
    return points


def delete_session(db: OrmSession, session_id: int) -> bool:
    """Delete one session and everything under it (questions/answers/metrics/
    scores/feedback/report cascade via the ORM relationships). Returns True
    if a row was deleted."""
    row = db.get(models.Session, session_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def delete_all_sessions(db: OrmSession) -> int:
    """Delete every session (and cascaded children). Returns the count."""
    rows = db.scalars(select(models.Session)).all()
    count = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()
    return count


def get_bank_items(
    db: OrmSession, role: str, seniority: str, jd_hash: str
) -> list[models.QuestionBankItem]:
    """Cached question-bank rows matching (role, seniority, jd_hash) — the
    same key the /api/question-bank endpoint saves under, so a pre-generated
    or previously-generated bank is reused instead of re-asking the LLM."""
    stmt = select(models.QuestionBankItem).where(
        models.QuestionBankItem.role == role,
        models.QuestionBankItem.seniority == seniority,
        models.QuestionBankItem.source_jd_hash == jd_hash,
    )
    return list(db.scalars(stmt).all())


def get_bank_items_by_ids(db: OrmSession, ids: list[int]) -> list[models.QuestionBankItem]:
    """Fetch bank rows by id, preserving the caller's requested order (drill mode)."""
    if not ids:
        return []
    rows = {r.id: r for r in db.scalars(
        select(models.QuestionBankItem).where(models.QuestionBankItem.id.in_(ids))
    ).all()}
    return [rows[i] for i in ids if i in rows]


def save_bank_items(
    db: OrmSession,
    role: str,
    seniority: str,
    jd_hash: str,
    questions: list[GeneratedQuestion],
) -> list[models.QuestionBankItem]:
    """Persist questions to the bank, idempotently by text: a question whose
    text already exists for this (role, seniority) returns the existing row
    instead of inserting a duplicate — so re-clicking "Add HR set" / "Drill
    this question" / re-generating an overlapping set never bloats the bank,
    and the returned ids stay stable across clicks. Order matches `questions`."""
    out: list[models.QuestionBankItem] = []
    new_rows: list[models.QuestionBankItem] = []
    for q in questions:
        existing = db.scalars(
            select(models.QuestionBankItem).where(
                func.lower(models.QuestionBankItem.text) == q.text.strip().lower(),
                models.QuestionBankItem.role == role,
                models.QuestionBankItem.seniority == seniority,
            )
        ).first()
        if existing is not None:
            out.append(existing)
            continue
        row = models.QuestionBankItem(
            role=role,
            seniority=seniority,
            category=q.category,
            text=q.text,
            targets_competency=q.targets_competency,
            difficulty=q.difficulty,
            source_jd_hash=jd_hash,
        )
        db.add(row)
        new_rows.append(row)
        out.append(row)
    db.commit()
    for row in new_rows:
        db.refresh(row)
    return out


def get_recent_question_texts(
    db: OrmSession, role: str, limit_sessions: int = 10
) -> set[str]:
    """Lowercased question texts asked (any session status) for this role in
    the most recent N sessions — used to keep a fresh session from repeating
    what the candidate was just asked."""
    recent_session_ids = db.scalars(
        select(models.Session.id)
        .where(models.Session.role == role)
        .order_by(models.Session.created_at.desc())
        .limit(limit_sessions)
    ).all()
    if not recent_session_ids:
        return set()
    texts = db.scalars(
        select(models.Question.text).where(models.Question.session_id.in_(recent_session_ids))
    ).all()
    return {t.strip().lower() for t in texts}


def get_weak_competencies(db: OrmSession, role: str, limit: int = 3) -> list[dict]:
    """The `limit` competencies with the lowest average overall score for this
    role, each with its average — feeds Adaptive mode's question weighting."""
    stmt = (
        select(models.Question.targets_competency, func.avg(models.Score.overall))
        .join(models.Answer, models.Answer.question_id == models.Question.id)
        .join(models.Score, models.Score.answer_id == models.Answer.id)
        .join(models.Session, models.Session.id == models.Question.session_id)
        .where(models.Session.role == role, models.Question.targets_competency != "")
        .group_by(models.Question.targets_competency)
        .having(func.count(models.Score.id) >= 1)
    )
    rows = [(name, avg) for name, avg in db.execute(stmt).all() if name]
    rows.sort(key=lambda r: r[1])
    return [{"competency": name, "avg_overall": round(avg, 2)} for name, avg in rows[:limit]]


def get_question_text(db: OrmSession, question_id: int) -> Optional[str]:
    row = db.get(models.Question, question_id)
    return row.text if row is not None else None


def get_question(db: OrmSession, question_id: int) -> Optional[models.Question]:
    return db.get(models.Question, question_id)


def get_answer_transcript(db: OrmSession, question_id: int) -> Optional[str]:
    """The candidate's most recent transcript for a question — lets the
    "strong answer" coach rewrite THEIR answer instead of writing a generic
    ideal one. Picks the latest answer if the question was retried."""
    row = db.scalars(
        select(models.Answer)
        .where(models.Answer.question_id == question_id)
        .order_by(models.Answer.id.desc())
        .limit(1)
    ).first()
    return row.transcript if row is not None else None


def get_app_setting(db: OrmSession, key: str) -> Optional[str]:
    row = db.get(models.AppSetting, key)
    return row.value if row is not None else None


def set_app_setting(db: OrmSession, key: str, value: str) -> None:
    row = db.get(models.AppSetting, key)
    if row is None:
        db.add(models.AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def list_bank_items(db: OrmSession, limit: int = 100) -> list[models.QuestionBankItem]:
    """Newest-first bank items across all roles — the interview setup page's
    Drill question picker."""
    return list(
        db.scalars(
            select(models.QuestionBankItem)
            .order_by(models.QuestionBankItem.id.desc())
            .limit(limit)
        ).all()
    )


def get_random_bank_item(db: OrmSession) -> Optional[models.QuestionBankItem]:
    """One random question from the bank — Home's "question of the day"."""
    return db.scalars(
        select(models.QuestionBankItem).order_by(func.random()).limit(1)
    ).first()


def get_previous_attempt(
    db: OrmSession, question_text: str, before_session_id: int
) -> Optional[dict]:
    """The most recent EARLIER-session scored answer to the same question
    text (case-insensitive) — powers Drill mode's "vs last attempt" delta.
    Returns None if this is the first time the question has been answered.
    """
    stmt = (
        select(models.Question, models.Score, models.Session.created_at)
        .join(models.Answer, models.Answer.question_id == models.Question.id)
        .join(models.Score, models.Score.answer_id == models.Answer.id)
        .join(models.Session, models.Session.id == models.Question.session_id)
        .where(
            func.lower(func.trim(models.Question.text)) == question_text.strip().lower(),
            models.Question.session_id != before_session_id,
        )
        .order_by(models.Session.created_at.desc())
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row is None:
        return None
    _question, score, created_at = row
    return {
        "created_at": created_at.isoformat(),
        "overall": score.overall,
        "scores": {
            "content_relevance": score.content_score,
            "structure": score.structure_score,
            "specificity": score.specificity_score,
            "technical_accuracy": score.technical_accuracy,
            "delivery": score.delivery_score,
            "overall": score.overall,
        },
    }


def get_stats(db: OrmSession) -> StatsResult:
    """Cross-session aggregates for the dashboard's 'Filler habits' card.

    Scoped to completed sessions only, matching get_trends()'s scope.
    """
    completed_sessions = db.scalars(
        select(models.Session).where(models.Session.status == "completed")
    ).all()
    total_sessions = len(completed_sessions)
    total_practice_sec = sum(row.duration_sec or 0.0 for row in completed_sessions)

    answer_count_stmt = (
        select(func.count(models.Answer.id))
        .join(models.Question, models.Question.id == models.Answer.question_id)
        .join(models.Session, models.Session.id == models.Question.session_id)
        .where(models.Session.status == "completed")
    )
    total_answers = db.scalar(answer_count_stmt) or 0

    raw_jsons_stmt = (
        select(models.DeliveryMetricsRow.raw_json)
        .join(models.Answer, models.Answer.id == models.DeliveryMetricsRow.answer_id)
        .join(models.Question, models.Question.id == models.Answer.question_id)
        .join(models.Session, models.Session.id == models.Question.session_id)
        .where(models.Session.status == "completed")
    )
    filler_totals: dict[str, int] = defaultdict(int)
    for (raw_json,) in db.execute(raw_jsons_stmt).all():
        for word, count in (raw_json or {}).get("filler_words", {}).items():
            filler_totals[word] += count

    top_fillers = [
        FillerStat(word=word, count=count)
        for word, count in sorted(filler_totals.items(), key=lambda kv: kv[1], reverse=True)[:6]
    ]

    return StatsResult(
        total_sessions=total_sessions,
        total_answers=total_answers,
        total_practice_sec=round(total_practice_sec, 1),
        filler_totals=dict(filler_totals),
        top_fillers=top_fillers,
        competencies=get_competency_averages(db),
        readiness_score=get_readiness_score(db),
    )


def get_competency_averages(db: OrmSession) -> list[dict]:
    """Avg overall score by targets_competency across ALL roles/sessions —
    the dashboard's competency heatmap. Sorted worst-first: the weakest
    competency is the one most worth practicing next."""
    stmt = (
        select(
            models.Question.targets_competency,
            func.avg(models.Score.overall),
            func.count(models.Score.id),
        )
        .join(models.Answer, models.Answer.question_id == models.Question.id)
        .join(models.Score, models.Score.answer_id == models.Answer.id)
        .where(models.Question.targets_competency != "")
        .group_by(models.Question.targets_competency)
        .having(func.count(models.Score.id) >= 1)
    )
    rows = [(name, avg, count) for name, avg, count in db.execute(stmt).all() if name]
    rows.sort(key=lambda r: r[1])
    return [{"name": name, "avg": round(avg, 2), "count": count} for name, avg, count in rows]


def get_readiness_score(db: OrmSession) -> Optional[float]:
    """0-100 blend: last-5 completed sessions' avg overall (60%, scaled to
    0-100) + avg confidence_proxy (25%) + avg expressiveness (15%). None
    until at least one session has completed with a score."""
    recent = db.scalars(
        select(models.Session)
        .where(models.Session.status == "completed", models.Session.overall_score.is_not(None))
        .order_by(models.Session.created_at.desc())
        .limit(5)
    ).all()
    if not recent:
        return None
    avg_overall = sum(r.overall_score for r in recent) / len(recent)  # 0-10
    session_ids = [r.id for r in recent]

    conf_stmt = (
        select(func.avg(models.DeliveryMetricsRow.confidence_proxy))
        .join(models.Answer, models.Answer.id == models.DeliveryMetricsRow.answer_id)
        .join(models.Question, models.Question.id == models.Answer.question_id)
        .where(models.Question.session_id.in_(session_ids))
    )
    avg_conf = db.scalar(conf_stmt) or 0.0

    # expressiveness has no dedicated column — only lives in raw_json.
    raw_jsons_stmt = (
        select(models.DeliveryMetricsRow.raw_json)
        .join(models.Answer, models.Answer.id == models.DeliveryMetricsRow.answer_id)
        .join(models.Question, models.Question.id == models.Answer.question_id)
        .where(models.Question.session_id.in_(session_ids))
    )
    expr_values = [
        rj.get("expressiveness")
        for (rj,) in db.execute(raw_jsons_stmt).all()
        if rj and rj.get("expressiveness")
    ]
    avg_expr = sum(expr_values) / len(expr_values) if expr_values else 0.0

    score = (avg_overall * 10 * 0.60) + (avg_conf * 0.25) + (avg_expr * 0.15)
    return round(max(0.0, min(100.0, score)), 1)


def get_history_aggregates(
    db: OrmSession, exclude_session_id: int | None = None
) -> list[dict]:
    """Category averages + delivery averages for the last 3 completed sessions."""
    stmt = (
        select(models.Session)
        .where(models.Session.status == "completed")
        .order_by(models.Session.created_at.desc())
        .limit(3)
    )
    if exclude_session_id is not None:
        stmt = stmt.where(models.Session.id != exclude_session_id)
    rows = db.scalars(stmt).all()
    history: list[dict] = []
    for row in rows:
        history.append(
            {
                "session_id": row.id,
                "created_at": row.created_at.isoformat(),
                "overall_score": row.overall_score,
                "category_averages": _category_averages(_session_score_rows(db, row.id)),
                **_session_metric_averages(db, row.id),
            }
        )
    return history
