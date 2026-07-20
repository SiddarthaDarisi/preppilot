"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" width="26" height="26" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

/**
 * Large circular record button. Idle = accent mic; recording = red stop icon
 * with two expanding rings and a live mic-level glow ring driven by a rAF
 * loop reading meterLevelRef (same source as the bar meter). Reduced motion
 * is handled globally in globals.css.
 */
export default function RecordOrb({
  recording,
  canRecord,
  meterLevelRef,
  onStart,
  onStop,
}: {
  recording: boolean;
  canRecord: boolean;
  meterLevelRef: RefObject<number>;
  onStart: () => void;
  onStop: () => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!recording) return;
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
  }, [recording, meterLevelRef]);

  return (
    <div className="record-orb-wrap" ref={wrapRef}>
      {recording && (
        <>
          <div className="orb-ring" />
          <div className="orb-ring r2" />
          <div className="orb-level" />
        </>
      )}
      <button
        type="button"
        className={"record-orb" + (recording ? " recording" : "")}
        onClick={recording ? onStop : onStart}
        disabled={!recording && !canRecord}
        aria-label={recording ? "Stop answering" : "Start answering"}
        title={recording ? "Stop answering" : "Start answering"}
      >
        {recording ? <StopIcon /> : <MicIcon />}
      </button>
    </div>
  );
}
