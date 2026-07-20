"use client";

import { useEffect, useRef, useState } from "react";

const STATUS_LABELS: Record<string, string> = {
  listening: "Listening — go ahead and answer",
  transcribing: "Transcribing your answer…",
  analyzing: "Analyzing your delivery…",
  thinking: "Thinking…",
  speaking: "Interviewer is speaking…",
  done: "Session complete",
};

/**
 * Status strip for the interview turn state machine. For "thinking" (the
 * 30-60s local-LLM wait — see CLAUDE.md) it also shows an elapsed-time
 * counter, an indeterminate progress bar, and — once it's taken a while —
 * a hint that this is expected, so a quiet local model doesn't read as hung.
 */
export default function StatusStrip({
  state,
  detail,
}: {
  state: string;
  detail?: string;
}) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const startRef = useRef<number>(Date.now());
  const prevStateRef = useRef<string>(state);

  useEffect(() => {
    if (state !== prevStateRef.current) {
      startRef.current = Date.now();
      setElapsedMs(0);
      prevStateRef.current = state;
    }
  }, [state]);

  useEffect(() => {
    if (state !== "thinking") return;
    const id = setInterval(() => setElapsedMs(Date.now() - startRef.current), 500);
    return () => clearInterval(id);
  }, [state]);

  const isThinking = state === "thinking";
  const elapsedSec = Math.floor(elapsedMs / 1000);
  const showHint = isThinking && elapsedSec >= 10;

  return (
    <div className={"status-strip st-" + state}>
      <div className="status-strip-row">
        <span className="state-dot"></span>
        <span>{detail || STATUS_LABELS[state] || state}</span>
        {isThinking && elapsedSec > 0 && (
          <span className="elapsed">{elapsedSec}s</span>
        )}
      </div>
      {isThinking && (
        <div className="shimmer-track">
          <div className="shimmer-bar" />
        </div>
      )}
      {showHint && (
        <div className="hint">
          Running on a local 8B model — turns typically take 30–60s.
        </div>
      )}
    </div>
  );
}
