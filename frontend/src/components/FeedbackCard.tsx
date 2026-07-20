import type {
  DeliveryMetrics,
  FeedbackResult,
  PreviousAttempt,
  Scores,
  StarCompleteness,
} from "@/lib/types";
import ScoreBars from "@/components/ScoreBars";
import DeliveryPanel from "@/components/DeliveryPanel";

const SCORE_LABELS: [keyof Scores, string][] = [
  ["content_relevance", "Relevance"],
  ["structure", "Structure"],
  ["specificity", "Specificity"],
  ["technical_accuracy", "Tech accuracy"],
  ["delivery", "Delivery"],
  ["overall", "Overall"],
];

export function StarPills({
  star,
  small = false,
}: {
  star?: StarCompleteness;
  small?: boolean;
}) {
  const parts: [keyof StarCompleteness, string][] = [
    ["situation", "S"],
    ["task", "T"],
    ["action", "A"],
    ["result", "R"],
  ];
  return (
    <div className={"star-pills" + (small ? " sm" : "")}>
      {parts.map(([key, letter]) => {
        const lit = !!(star && star[key]);
        const title =
          key.charAt(0).toUpperCase() +
          key.slice(1) +
          (lit ? " — covered" : " — missing");
        return (
          <span
            key={key}
            className={"star-pill" + (lit ? " lit" : "")}
            title={title}
          >
            {letter}
          </span>
        );
      })}
    </div>
  );
}

function DeltaChip({ current, previous }: { current: number; previous: PreviousAttempt }) {
  const delta = current - previous.overall;
  const cls = delta > 0 ? "up" : delta < 0 ? "down" : "";
  const arrow = delta > 0 ? "▲" : delta < 0 ? "▼" : "=";
  return (
    <span
      className={"delta-chip" + (cls ? " " + cls : "")}
      title={`Last attempt: ${previous.overall}/10`}
    >
      {arrow} {delta === 0 ? "same" : Math.abs(delta)} vs last attempt
    </span>
  );
}

/** Per-answer feedback card: score bars, STAR pills, strengths, fixes. */
export default function FeedbackCard({
  qNum,
  feedback,
  metrics,
  isNew = false,
  previousAttempt = null,
  modelAnswer = null,
  modelAnswerLoading = false,
  onRequestModelAnswer,
}: {
  qNum: number;
  feedback: FeedbackResult;
  metrics: DeliveryMetrics | null;
  isNew?: boolean;
  previousAttempt?: PreviousAttempt | null;
  modelAnswer?: string | null;
  modelAnswerLoading?: boolean;
  onRequestModelAnswer?: () => void;
}) {
  const scores = feedback.scores || ({} as Scores);
  const scoreItems = SCORE_LABELS.filter(([key]) => scores[key] != null).map(
    ([key, label]) => ({ label, value: scores[key] as number }),
  );

  return (
    <div className={"card feedback-card" + (isNew ? " is-new" : "")}>
      <div className="question-meta">
        <span className="badge qnum">Q{qNum} feedback</span>
        {previousAttempt && (
          <DeltaChip current={scores.overall} previous={previousAttempt} />
        )}
      </div>

      <ScoreBars items={scoreItems} />

      {feedback.star_applicable !== false && (
        <>
          <div className="fb-section-title">STAR completeness</div>
          <StarPills star={feedback.star_completeness} />
        </>
      )}

      {Array.isArray(feedback.strengths) && feedback.strengths.length > 0 && (
        <>
          <div className="fb-section-title">Strengths</div>
          <ul className="plain-list">
            {feedback.strengths.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </>
      )}

      {Array.isArray(feedback.improvements) &&
        feedback.improvements.length > 0 && (
          <>
            <div className="fb-section-title">Improvements</div>
            {feedback.improvements.map((imp, i) => (
              <div className="improvement-item" key={i}>
                <span className="issue">{imp.issue || ""}</span>
                <span className="arrow">→</span>
                <span className="fix">{imp.fix || ""}</span>
              </div>
            ))}
          </>
        )}

      {feedback.delivery_feedback && (
        <>
          <div className="fb-section-title">Delivery</div>
          <p className="coaching-text">{feedback.delivery_feedback}</p>
        </>
      )}
      {feedback.coaching_summary && (
        <>
          <div className="fb-section-title">Coach&rsquo;s summary</div>
          <p className="coaching-text">{feedback.coaching_summary}</p>
        </>
      )}

      {metrics && (
        <>
          <div className="fb-section-title">Delivery metrics</div>
          <DeliveryPanel metrics={metrics} />
        </>
      )}

      {onRequestModelAnswer && (
        <details className="model-answer-disclosure">
          <summary
            onClick={() => {
              if (!modelAnswer && !modelAnswerLoading) onRequestModelAnswer();
            }}
          >
            {modelAnswerLoading ? "Rewriting your answer…" : "Show how I'd answer this"}
          </summary>
          {modelAnswer && <p className="coaching-text model-answer-text">{modelAnswer}</p>}
        </details>
      )}
    </div>
  );
}
