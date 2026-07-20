"""Shared Pydantic schemas — the contract between orchestrator, analytics,
providers, prompts, and the frontend. Every module builds against these.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

QuestionCategory = Literal["behavioral", "system_design", "technical_concept", "coding_concept"]


# ---------------------------------------------------------------- analytics

class DeliveryMetrics(BaseModel):
    """Interpretable per-answer delivery metrics (Phase 3)."""
    wpm: float = 0.0
    articulation_wpm: float = 0.0          # excludes pauses
    pause_ratio: float = 0.0               # silent time / total time
    long_pause_count: int = 0              # pauses > 1.5s
    filler_count: int = 0
    filler_rate: float = 0.0               # fillers / words
    filler_words: dict[str, int] = Field(default_factory=dict)
    pitch_mean_hz: float = 0.0
    pitch_std_hz: float = 0.0
    pitch_range_hz: float = 0.0
    energy_cv: float = 0.0                 # coefficient of variation of RMS
    duration_sec: float = 0.0
    word_count: int = 0
    confidence_proxy: float = 0.0          # 0-100, documented composite
    expressiveness: float = 0.0            # 0-100, tone-variety composite (see _expressiveness)
    ser_label: Optional[str] = None        # optional wav2vec2 SER
    ser_confidence: Optional[float] = None


class WordTiming(BaseModel):
    word: str
    start: float
    end: float


class TranscriptionResult(BaseModel):
    text: str
    words: list[WordTiming] = Field(default_factory=list)
    language: str = "en"
    duration_sec: float = 0.0


# ---------------------------------------------------------------- LLM outputs

class InterviewerTurn(BaseModel):
    """Structured output of the interviewer prompt."""
    question: str
    category: QuestionCategory = "behavioral"
    is_followup: bool = False
    targets_competency: str = ""
    rationale: str = ""


class StarCompleteness(BaseModel):
    situation: bool = False
    task: bool = False
    action: bool = False
    result: bool = False


class Scores(BaseModel):
    content_relevance: int = Field(5, ge=1, le=10)
    structure: int = Field(5, ge=1, le=10)
    specificity: int = Field(5, ge=1, le=10)
    technical_accuracy: Optional[int] = Field(None, ge=1, le=10)
    delivery: int = Field(5, ge=1, le=10)
    overall: int = Field(5, ge=1, le=10)

    # LLMs (qwen3:8b in particular) occasionally emit 0 or 11 despite the
    # prompt's explicit 1-10 instruction. Clamp instead of failing the whole
    # turn — a discarded/repaired feedback response is worse UX than a score
    # nudged to the nearest valid bound.
    @field_validator(
        "content_relevance", "structure", "specificity", "technical_accuracy", "delivery", "overall",
        mode="before",
    )
    @classmethod
    def _clamp_score(cls, v: Any) -> Any:
        if v is None:
            return None
        try:
            n = round(float(v))
        except (TypeError, ValueError):
            return v
        return max(1, min(10, n))


class Improvement(BaseModel):
    issue: str
    fix: str


class FeedbackResult(BaseModel):
    """Structured output of the coaching prompt."""
    scores: Scores = Field(default_factory=Scores)
    # STAR only applies to story/experience behavioral questions ("tell me
    # about a time..."). Direct/screening questions (salary expectations,
    # "tell me about yourself", "why this company", strengths/weaknesses)
    # are not STAR — the coach sets this False and the UI hides the STAR pills
    # so the candidate isn't told to add a "Situation" to a salary answer.
    star_applicable: bool = True
    star_completeness: StarCompleteness = Field(default_factory=StarCompleteness)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[Improvement] = Field(default_factory=list)
    delivery_feedback: str = ""
    coaching_summary: str = ""


class GeneratedQuestion(BaseModel):
    category: QuestionCategory
    text: str
    targets_competency: str = ""
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    id: Optional[int] = None  # set once persisted to the bank; used to drill/practice it later


class QuestionBankResult(BaseModel):
    questions: list[GeneratedQuestion] = Field(default_factory=list)


class DeliverySummary(BaseModel):
    avg_wpm: float = 0.0
    avg_filler_rate: float = 0.0
    avg_confidence: float = 0.0
    biggest_habit_to_fix: str = ""


class PracticePlanItem(BaseModel):
    focus: str
    drill: str
    target_metric: str = ""


class ReportResult(BaseModel):
    """Structured output of the end-of-session report prompt."""
    overall_score: float = 0.0
    category_scores: dict[str, float] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    development_areas: list[str] = Field(default_factory=list)
    delivery_summary: DeliverySummary = Field(default_factory=DeliverySummary)
    trends: Optional[dict[str, str]] = None
    practice_plan: list[PracticePlanItem] = Field(default_factory=list)


# ---------------------------------------------------------------- REST API

class SessionCreateRequest(BaseModel):
    role: str = "Software Engineer"
    seniority: Literal["junior", "mid", "senior", "staff"] = "mid"
    jd_text: str = ""
    focus_areas: list[str] = Field(default_factory=lambda: ["behavioral", "system_design"])
    max_questions: Optional[int] = None
    # adaptive: cross-session memory, never repeats recent questions, biases
    #           toward weak competencies.
    # drill:    repeats exactly `bank_ids`, in order, on purpose.
    # full:     same pooling as adaptive; the Full Interview page drives
    #           hands-free turn-taking via set_options.
    mode: Literal["adaptive", "drill", "full"] = "adaptive"
    bank_ids: Optional[list[int]] = None
    # neutral: professional senior-panelist tone (unchanged default behavior).
    # friendly: warm and encouraging. tough: skeptical, pushes on weak answers.
    persona: Literal["neutral", "friendly", "tough"] = "neutral"


class SessionSummary(BaseModel):
    id: int
    created_at: datetime
    role: str
    seniority: str
    status: str
    mode: str = "adaptive"
    overall_score: Optional[float] = None
    question_count: int = 0
    duration_sec: Optional[float] = None
    provider: str = ""
    model: str = ""


class AnswerRecord(BaseModel):
    question_id: int
    question: str
    category: str
    is_followup: bool
    transcript: str
    metrics: Optional[DeliveryMetrics] = None
    feedback: Optional[FeedbackResult] = None


class SessionDetail(BaseModel):
    summary: SessionSummary
    answers: list[AnswerRecord] = Field(default_factory=list)
    report: Optional[ReportResult] = None


class FillerStat(BaseModel):
    word: str
    count: int


class CompetencyAvg(BaseModel):
    """One row of the dashboard's competency heatmap (worst-first)."""
    name: str
    avg: float
    count: int


class StatsResult(BaseModel):
    """Cross-session aggregate for the dashboard's 'Filler habits' card."""
    total_sessions: int = 0
    total_answers: int = 0
    total_practice_sec: float = 0.0
    filler_totals: dict[str, int] = Field(default_factory=dict)
    top_fillers: list[FillerStat] = Field(default_factory=list)  # sorted desc, max 6
    competencies: list[CompetencyAvg] = Field(default_factory=list)  # worst avg first
    # 0-100 blend: last-5 sessions' avg overall (60%) + avg confidence_proxy
    # (25%) + avg expressiveness (15%). None until at least one session
    # completes.
    readiness_score: Optional[float] = None


class TrendPoint(BaseModel):
    session_id: int
    created_at: datetime
    overall_score: Optional[float] = None
    category_scores: dict[str, float] = Field(default_factory=dict)
    avg_wpm: Optional[float] = None
    avg_filler_rate: Optional[float] = None
    avg_confidence: Optional[float] = None
    avg_expressiveness: Optional[float] = None


# ---------------------------------------------------------------- WebSocket protocol
# Server -> client messages: {"type": ..., ...}
#   resumed            {answered_count}   (sent once, only on a reconnect to an
#                                          in-progress session, before the next
#                                          question/report message)
#   question           {text, category, is_followup, order_idx, max_questions, audio_b64?}
#     max_questions is server-authoritative (Drill mode overrides the client's
#     session-create guess to len(bank_ids)) — always trust this over any
#     client-side count.
#   transcript_interim {text}
#   transcript_final   {text}
#   ack                {audio_b64}   (voice mode only; a short spoken
#                                     acknowledgment played immediately after
#                                     transcript_final, before the scoring LLM
#                                     call — keeps Full Interview mode feeling
#                                     responsive instead of going silent)
#   metrics            {DeliveryMetrics}   (sent in BOTH voice and text mode, before feedback)
#   feedback           {FeedbackResult, question_id, previous_attempt?}
#     previous_attempt {created_at, overall, scores}   (only present when this
#                        exact question text was answered in an earlier
#                        session — Drill mode's "vs last attempt" delta)
#   report             {ReportResult}
#   status             {state: listening|transcribing|analyzing|thinking|speaking|done, detail?}
#   model_answer       {question_id, text}   ("Show a strong answer" — a cached, on-demand
#                                             exemplary answer for one question; sent only in
#                                             reply to the client's model_answer request)
#   await_action       {session_complete}   (manual-advance/practice mode only: sent after
#                                            feedback instead of auto-advancing. The client shows
#                                            "Try again" / "Next question" — or "See report" when
#                                            session_complete is true. Client replies with
#                                            retry_question or next_question.)
#   error              {message, code?}   (code: "empty_transcript" is the only value so far —
#                                          the current question stays open, client should let
#                                          the user retry rather than treat it like a fatal error)
# Client -> server:
#   binary frames      16kHz mono PCM16 audio
#   {"type": "answer_text", "text": ...}   (text mode / Phase 1)
#   {"type": "end_turn"}                   (manual end-of-turn button)
#   {"type": "end_session"}
#   {"type": "set_options", "auto_end_turn": bool, "end_of_turn_silence_ms"?: int}
#     Controls the voice turn-detector for this connection. The practice tab
#     sends auto_end_turn=false on connect (fixes the "cuts me off" bug — the
#     turn only ends on end_turn/Done). Full Interview mode sends
#     auto_end_turn=true with end_of_turn_silence_ms=2500 for hands-free
#     turn-taking. end_of_turn_silence_ms is clamped to [500, 10000].
#   {"type": "model_answer", "question_id": int}
#     Requests a one-off exemplary answer for a past question (button on
#     FeedbackCard). Answered asynchronously via the model_answer server message.
#   {"type": "next_question"}     (manual-advance/practice mode: move on after an await_action)
#   {"type": "retry_question"}    (manual-advance/practice mode: re-answer the SAME question)
#   {"type": "rephrase_question"} (manual-advance/practice mode: re-ask the same question reworded
#                                  into different words — same competency; doesn't consume a slot)
#   set_options also accepts "manual_advance": bool — the practice tab sends true so the
#     server waits (await_action) after feedback instead of auto-advancing.


class WSMessage(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)
