"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";

export type OrbState = "idle" | "speaking" | "listening" | "thinking";

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
    </svg>
  );
}

function WaveIcon() {
  return (
    <svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <line x1="4" y1="10" x2="4" y2="14" />
      <line x1="8" y1="6" x2="8" y2="18" />
      <line x1="12" y1="3" x2="12" y2="21" />
      <line x1="16" y1="6" x2="16" y2="18" />
      <line x1="20" y1="10" x2="20" y2="14" />
    </svg>
  );
}

function DotsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor">
      <circle cx="6" cy="12" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="18" cy="12" r="2" />
    </svg>
  );
}

const LABELS: Record<OrbState, string> = {
  idle: "Ready",
  speaking: "Interviewer speaking",
  listening: "Listening — tap to finish your answer",
  thinking: "Thinking",
};

/**
 * The Full Interview stage centerpiece. Generalizes RecordOrb into four
 * states instead of a binary recording toggle: speaking (interviewer's TTS
 * is playing), listening (mic open, hands-free auto end-of-turn), thinking
 * (waiting on the LLM), idle (nothing happening yet / paused). Only
 * "listening" is clickable (force-ends the turn early, same as the practice
 * tab's Done button) — the other states are just visual feedback.
 */
export default function VoiceOrb({
  state,
  meterLevelRef,
  onClick,
}: {
  state: OrbState;
  meterLevelRef: RefObject<number>;
  onClick?: () => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (state !== "listening") return;
    const wrap = wrapRef.current;
    if (!wrap) return;
    let raf = 0;
    const tick = () => {
      const level = Math.min(1, (meterLevelRef.current || 0) * 4);
      wrap.style.setProperty("--level", String(level));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [state, meterLevelRef]);

  const clickable = state === "listening" && !!onClick;
  const label = LABELS[state];

  return (
    <div className={`voice-orb-wrap orb-${state}`} ref={wrapRef}>
      {state === "listening" && (
        <>
          <div className="orb-ring" />
          <div className="orb-ring r2" />
          <div className="orb-level" />
        </>
      )}
      {state === "speaking" && <div className="orb-speak-glow" />}
      {state === "thinking" && <div className="orb-think-shimmer" />}
      <button
        type="button"
        className="voice-orb"
        onClick={clickable ? onClick : undefined}
        disabled={!clickable}
        aria-label={label}
        title={label}
      >
        {state === "speaking" ? <WaveIcon /> : state === "thinking" ? <DotsIcon /> : <MicIcon />}
      </button>
    </div>
  );
}
