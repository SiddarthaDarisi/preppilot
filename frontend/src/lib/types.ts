/**
 * PrepPilot — TypeScript mirrors of the backend Pydantic schemas
 * (backend/schemas.py) plus the WebSocket message shapes.
 */

export type QuestionCategory =
  | "behavioral"
  | "system_design"
  | "technical_concept"
  | "coding_concept";

export type Seniority = "junior" | "mid" | "senior" | "staff";

// ---------------------------------------------------------------- analytics

export interface DeliveryMetrics {
  wpm: number;
  articulation_wpm: number;
  pause_ratio: number;
  long_pause_count: number;
  filler_count: number;
  filler_rate: number;
  filler_words: Record<string, number>;
  pitch_mean_hz: number;
  pitch_std_hz: number;
  pitch_range_hz: number;
  energy_cv: number;
  duration_sec: number;
  word_count: number;
  confidence_proxy: number;
  expressiveness: number;
  ser_label?: string | null;
  ser_confidence?: number | null;
}

// ---------------------------------------------------------------- feedback

export interface StarCompleteness {
  situation: boolean;
  task: boolean;
  action: boolean;
  result: boolean;
}

export interface Scores {
  content_relevance: number;
  structure: number;
  specificity: number;
  technical_accuracy?: number | null;
  delivery: number;
  overall: number;
}

/** Drill mode: this exact question was answered in an earlier session too. */
export interface PreviousAttempt {
  created_at: string;
  overall: number;
  scores: Scores;
}

export interface Improvement {
  issue: string;
  fix: string;
}

export interface FeedbackResult {
  scores: Scores;
  star_applicable?: boolean;
  star_completeness: StarCompleteness;
  strengths: string[];
  improvements: Improvement[];
  delivery_feedback: string;
  coaching_summary: string;
}

// ---------------------------------------------------------------- report

export interface DeliverySummary {
  avg_wpm: number;
  avg_filler_rate: number;
  avg_confidence: number;
  biggest_habit_to_fix: string;
}

export interface PracticePlanItem {
  focus: string;
  drill: string;
  target_metric?: string;
}

export interface ReportResult {
  overall_score: number;
  category_scores: Record<string, number>;
  strengths: string[];
  development_areas: string[];
  delivery_summary: DeliverySummary;
  trends?: Record<string, string> | null;
  practice_plan: PracticePlanItem[];
}

// ---------------------------------------------------------------- question bank

export interface GeneratedQuestion {
  category: QuestionCategory;
  text: string;
  targets_competency: string;
  difficulty: "easy" | "medium" | "hard";
  id?: number | null;
}

export interface QuestionBankResult {
  questions: GeneratedQuestion[];
}

/** One saved bank row (GET /api/question-bank/items) — the Drill picker. */
export interface BankItem {
  id: number;
  text: string;
  category: string;
  difficulty: string;
  role: string;
  seniority: string;
  targets_competency: string;
}

export interface QuestionBankRequest {
  role: string;
  seniority: string;
  jd_text: string;
  n_behavioral: number;
  n_system_design: number;
  n_technical: number;
}

// ---------------------------------------------------------------- REST API

export type SessionMode = "adaptive" | "drill" | "full";

export type InterviewerPersona = "neutral" | "friendly" | "tough";

export interface SessionCreateRequest {
  role: string;
  seniority: Seniority;
  jd_text: string;
  focus_areas: string[];
  max_questions: number | null;
  mode?: SessionMode;
  bank_ids?: number[] | null;
  persona?: InterviewerPersona;
}

export interface SessionSummary {
  id: number;
  created_at: string;
  role: string;
  seniority: string;
  status: string;
  mode?: string;
  overall_score?: number | null;
  question_count: number;
  duration_sec?: number | null;
  provider: string;
  model: string;
}

export interface AnswerRecord {
  question_id: number;
  question: string;
  category: string;
  is_followup: boolean;
  transcript: string;
  metrics?: DeliveryMetrics | null;
  feedback?: FeedbackResult | null;
}

export interface SessionDetail {
  summary: SessionSummary;
  answers: AnswerRecord[];
  report?: ReportResult | null;
}

export interface FillerStat {
  word: string;
  count: number;
}

export interface CompetencyAvg {
  name: string;
  avg: number;
  count: number;
}

export interface StatsResult {
  total_sessions: number;
  total_answers: number;
  total_practice_sec: number;
  filler_totals: Record<string, number>;
  top_fillers: FillerStat[];
  competencies: CompetencyAvg[];
  readiness_score?: number | null;
}

export interface TrendPoint {
  session_id: number;
  created_at: string;
  overall_score?: number | null;
  category_scores: Record<string, number>;
  avg_wpm?: number | null;
  avg_filler_rate?: number | null;
  avg_confidence?: number | null;
  avg_expressiveness?: number | null;
}

// ---------------------------------------------------------------- settings

export interface VoiceOption {
  id: string;
  label: string;
  description: string;
}

export interface AppSettings {
  tts_voice: string;
  tts_backend: string;
  voices: VoiceOption[];
}

export interface HealthFlags {
  demo_llm: boolean;
  stt_missing: boolean;
  vad_missing: boolean;
  tts_missing: boolean;
}

export interface HealthInfo {
  llm_provider: string;
  llm_model: string;
  stt_backend: string;
  tts_backend: string;
  degraded?: string[];
  flags?: HealthFlags;
}

// ---------------------------------------------------------------- WebSocket

export type StatusState =
  | "listening"
  | "transcribing"
  | "analyzing"
  | "thinking"
  | "speaking"
  | "done";

export interface QuestionMessage {
  type: "question";
  text?: string;
  category?: QuestionCategory;
  is_followup?: boolean;
  order_idx?: number;
  max_questions?: number;
  audio_b64?: string;
}

/** Server -> client message (loosely typed; payload shape varies by type). */
export interface ServerMessage {
  type: string;
  // resumed (sent once, only on a reconnect to an in-progress session)
  answered_count?: number;
  // question
  text?: string;
  category?: QuestionCategory;
  is_followup?: boolean;
  order_idx?: number;
  max_questions?: number;
  audio_b64?: string;
  // metrics
  metrics?: DeliveryMetrics;
  // feedback (tolerate multiple payload shapes)
  feedback?: FeedbackResult;
  FeedbackResult?: FeedbackResult;
  question_id?: number;
  previous_attempt?: PreviousAttempt;
  // report
  report?: ReportResult;
  ReportResult?: ReportResult;
  // status
  state?: StatusState;
  detail?: string;
  // await_action (manual-advance / practice mode)
  session_complete?: boolean;
  // error
  message?: string;
  code?: string;
}
