"use client";

import { useState } from "react";
import { humanize } from "@/lib/format";

function SpeakerIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="4 8 8 8 13 4 13 20 8 16 4 16" />
      <path d="M17 8a5 5 0 0 1 0 8" />
    </svg>
  );
}

// Zero-LLM scaffolding, Google Interview Warmup style — a static per-category
// nudge, not a generated answer, so it never costs a round trip.
const HINTS: Record<string, string> = {
  behavioral:
    "STAR it: Situation (set the scene in 1-2 sentences) → Task (your specific responsibility) → Action (what YOU did, step by step) → Result (the outcome, ideally with a number).",
  system_design:
    "Start with requirements and scale numbers (users, QPS, data size) before design. Sketch the high-level components, then go deep on the one or two pieces that matter most for this question.",
  technical_concept:
    "Define it in one sentence, contrast it with a related concept, then give a concrete example of when you'd use it (and when you wouldn't).",
  coding_concept:
    "Talk through your approach before code: constraints, edge cases, and complexity. Then walk the logic step by step.",
};

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polygon points="12 2.5 15.1 8.9 22.1 9.9 17 14.8 18.3 21.8 12 18.4 5.7 21.8 7 14.8 1.9 9.9 8.9 8.9" />
    </svg>
  );
}

export default function QuestionCard({
  qNum,
  maxQuestions,
  category,
  isFollowup,
  text,
  canReplay = false,
  speaking = false,
  onReplay,
  onBookmark,
  bookmarked = false,
}: {
  qNum: number;
  maxQuestions?: number;
  category: string;
  isFollowup: boolean;
  text: string;
  canReplay?: boolean;
  speaking?: boolean;
  onReplay?: () => void;
  onBookmark?: () => void;
  bookmarked?: boolean;
}) {
  const [showHint, setShowHint] = useState(false);
  const hint = HINTS[category] || HINTS.behavioral;

  return (
    <div className="question-card">
      <div className="question-header-row">
        <div className="question-meta">
          <span className="badge qnum">
            Q{qNum}
            {maxQuestions ? ` of ${maxQuestions}` : ""}
          </span>
          <span className={"badge cat-" + category}>{humanize(category)}</span>
          {isFollowup && <span className="badge followup">follow-up</span>}
        </div>
        <div className="question-header-actions">
          {onBookmark && (
            <button
              type="button"
              className={"bookmark-btn" + (bookmarked ? " active" : "")}
              onClick={onBookmark}
              disabled={bookmarked}
              title={bookmarked ? "Saved to question bank" : "Save this question to drill later"}
              aria-label="Bookmark this question"
            >
              <StarIcon filled={bookmarked} />
            </button>
          )}
          {canReplay && (
            <button
              type="button"
              className={"replay-btn" + (speaking ? " speaking" : "")}
              onClick={onReplay}
              disabled={!onReplay}
              title="Replay question audio"
              aria-label="Replay question audio"
            >
              <SpeakerIcon />
            </button>
          )}
        </div>
      </div>
      <p className="question-text">
        {text || "Waiting for the first question…"}
      </p>
      {text && (
        <>
          <button type="button" className="hint-toggle" onClick={() => setShowHint((v) => !v)}>
            {showHint ? "Hide hint" : "Need a hint?"}
          </button>
          {showHint && <p className="hint-scaffold">{hint}</p>}
        </>
      )}
    </div>
  );
}
