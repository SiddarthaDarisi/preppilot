"use client";

import { useEffect, useRef, useState } from "react";

const TARGET_SEC = 120; // 2:00 soft target
const OVER_SEC = 150; // 2:30 — turns amber

/** Live elapsed-time readout for the current answer turn. Resets whenever
 * `resetKey` changes; only ticks while `active` (server status: listening).
 * `autoSubmitAtSec` (Rapid Round) fires `onAutoSubmit` once, the instant
 * elapsed time reaches it. */
export default function AnswerTimer({
  active,
  resetKey,
  autoSubmitAtSec,
  onAutoSubmit,
}: {
  active: boolean;
  resetKey: string | number;
  autoSubmitAtSec?: number;
  onAutoSubmit?: () => void;
}) {
  const [seconds, setSeconds] = useState(0);
  const firedRef = useRef(false);

  useEffect(() => {
    setSeconds(0);
    firedRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  useEffect(() => {
    if (!active) return;
    const start = Date.now() - seconds * 1000;
    const id = setInterval(() => setSeconds(Math.round((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    if (!autoSubmitAtSec || firedRef.current) return;
    if (seconds >= autoSubmitAtSec) {
      firedRef.current = true;
      onAutoSubmit?.();
    }
  }, [seconds, autoSubmitAtSec, onAutoSubmit]);

  const mm = Math.floor(seconds / 60);
  const ss = seconds % 60;
  const over = seconds >= OVER_SEC;
  const pct = Math.min(1, seconds / (autoSubmitAtSec || TARGET_SEC));

  return (
    <span
      className={"answer-timer" + (over ? " over" : "")}
      title={
        autoSubmitAtSec
          ? `Rapid Round — auto-submits at ${autoSubmitAtSec}s`
          : "Time on this answer — soft target 2:00"
      }
    >
      <svg viewBox="0 0 20 20" width="14" height="14">
        <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
        <circle
          cx="10"
          cy="10"
          r="8"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray={2 * Math.PI * 8}
          strokeDashoffset={2 * Math.PI * 8 * (1 - pct)}
          transform="rotate(-90 10 10)"
        />
      </svg>
      {mm}:{String(ss).padStart(2, "0")}
    </span>
  );
}
