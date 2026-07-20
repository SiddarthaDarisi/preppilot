"""SQLAlchemy 2.0 models — mirrors the spec's data model (§2.5)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Text, JSON, Float, Integer, String, Boolean, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    role: Mapped[str] = mapped_column(String(200), default="Software Engineer")
    seniority: Mapped[str] = mapped_column(String(50), default="mid")
    jd_text: Mapped[str] = mapped_column(Text, default="")
    focus_areas: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    provider: Mapped[str] = mapped_column(String(50), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|completed|abandoned
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default="adaptive")  # adaptive|drill|full
    persona: Mapped[str] = mapped_column(String(20), default="neutral")  # neutral|friendly|tough

    questions: Mapped[list["Question"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    report: Mapped["Report | None"] = relationship(back_populates="session", uselist=False, cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    order_idx: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(50), default="behavioral")
    text: Mapped[str] = mapped_column(Text)
    is_followup: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    targets_competency: Mapped[str] = mapped_column(String(100), default="")

    session: Mapped["Session"] = relationship(back_populates="questions")
    answer: Mapped["Answer | None"] = relationship(back_populates="question", uselist=False, cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    transcript: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    question: Mapped["Question"] = relationship(back_populates="answer")
    metrics: Mapped["DeliveryMetricsRow | None"] = relationship(back_populates="answer", uselist=False, cascade="all, delete-orphan")
    score: Mapped["Score | None"] = relationship(back_populates="answer", uselist=False, cascade="all, delete-orphan")
    feedback: Mapped["Feedback | None"] = relationship(back_populates="answer", uselist=False, cascade="all, delete-orphan")


class DeliveryMetricsRow(Base):
    __tablename__ = "delivery_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id"))
    wpm: Mapped[float] = mapped_column(Float, default=0)
    pause_ratio: Mapped[float] = mapped_column(Float, default=0)
    long_pause_count: Mapped[int] = mapped_column(Integer, default=0)
    filler_count: Mapped[int] = mapped_column(Integer, default=0)
    filler_rate: Mapped[float] = mapped_column(Float, default=0)
    pitch_mean: Mapped[float] = mapped_column(Float, default=0)
    pitch_std: Mapped[float] = mapped_column(Float, default=0)
    energy_cv: Mapped[float] = mapped_column(Float, default=0)
    confidence_proxy: Mapped[float] = mapped_column(Float, default=0)
    ser_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ser_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)  # full DeliveryMetrics dump

    answer: Mapped["Answer"] = relationship(back_populates="metrics")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id"))
    content_score: Mapped[int] = mapped_column(Integer, default=5)
    structure_score: Mapped[int] = mapped_column(Integer, default=5)
    specificity_score: Mapped[int] = mapped_column(Integer, default=5)
    star_completeness: Mapped[dict] = mapped_column(JSON, default=dict)
    delivery_score: Mapped[int] = mapped_column(Integer, default=5)
    technical_accuracy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall: Mapped[int] = mapped_column(Integer, default=5)

    answer: Mapped["Answer"] = relationship(back_populates="score")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id"))
    strengths_json: Mapped[list] = mapped_column(JSON, default=list)
    improvements_json: Mapped[list] = mapped_column(JSON, default=list)
    coaching_text: Mapped[str] = mapped_column(Text, default="")
    rubric_json: Mapped[dict] = mapped_column(JSON, default=dict)  # full FeedbackResult dump

    answer: Mapped["Answer"] = relationship(back_populates="feedback")


class QuestionBankItem(Base):
    __tablename__ = "question_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(200), default="")
    seniority: Mapped[str] = mapped_column(String(50), default="")
    category: Mapped[str] = mapped_column(String(50), default="behavioral")
    text: Mapped[str] = mapped_column(Text)
    targets_competency: Mapped[str] = mapped_column(String(100), default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    source_jd_hash: Mapped[str] = mapped_column(String(64), default="")


class AppSetting(Base):
    """Runtime-adjustable app settings (e.g. the interviewer's TTS voice),
    persisted server-side — the frontend is a static export with no
    localStorage, so the server is the settings store. Loaded over the
    config-file value at startup; config.yaml stays the cold-start default."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)      # full ReportResult dump
    practice_plan_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped["Session"] = relationship(back_populates="report")
