"use client";

import { useEffect, useRef } from "react";
import type { ReactNode, RefObject } from "react";
import TranscriptText from "@/components/TranscriptText";
import RecordOrb from "@/components/RecordOrb";

/**
 * Voice answer area: record / done controls, mic level meter and the live
 * transcript box. Audio capture itself lives in the page; this component is
 * presentational plus the meter's rAF drawing loop (fed by meterLevelRef).
 */
export default function Recorder({
  recording,
  canRecord,
  finalTranscript,
  interimTranscript,
  meterLevelRef,
  onStart,
  onDone,
  onEndSession,
  endDisabled = false,
  notice = null,
  timerSlot = null,
}: {
  recording: boolean;
  canRecord: boolean;
  finalTranscript: string;
  interimTranscript: string;
  meterLevelRef: RefObject<number>;
  onStart: () => void;
  onDone: () => void;
  onEndSession: () => void;
  endDisabled?: boolean;
  notice?: string | null;
  timerSlot?: ReactNode;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Mic level meter loop while recording.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    if (!recording) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    // Canvas fillStyle can't take var(...) directly — read the resolved
    // theme colors once per draw so the meter follows the dark/light toggle.
    const rootStyle = getComputedStyle(document.documentElement);
    const colorGreen = rootStyle.getPropertyValue("--green").trim() || "#34c98e";
    const colorAmber = rootStyle.getPropertyValue("--amber").trim() || "#f0b13d";
    const colorRed = rootStyle.getPropertyValue("--red").trim() || "#f2607a";

    let raf = 0;
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      // Map RMS (~0..0.3 speech range) to bar width with soft compression.
      const level = Math.min(1, (meterLevelRef.current || 0) * 4);
      const w = level * (canvas.width - 8);
      const grad = ctx.createLinearGradient(0, 0, canvas.width, 0);
      grad.addColorStop(0, colorGreen);
      grad.addColorStop(0.7, colorAmber);
      grad.addColorStop(1, colorRed);
      ctx.fillStyle = grad;
      ctx.fillRect(4, 8, w, canvas.height - 16);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [recording, meterLevelRef]);

  return (
    <div className="answer-area card">
      <div className="orb-controls">
        <RecordOrb
          recording={recording}
          canRecord={canRecord}
          meterLevelRef={meterLevelRef}
          onStart={onStart}
          onStop={onDone}
        />
        <div className="orb-caption">
          {recording ? "Recording — tap to finish" : canRecord ? "Tap to answer" : "Waiting…"}
        </div>
        {timerSlot}
        <canvas ref={canvasRef} className="mic-meter" width={160} height={24} />
      </div>
      <div className="transcript-box">
        {!finalTranscript && !interimTranscript ? (
          <span className="placeholder">
            Your live transcript will appear here.
          </span>
        ) : (
          <>
            {finalTranscript && (
              <span className="final">
                <TranscriptText text={finalTranscript} />
                {interimTranscript ? " " : ""}
              </span>
            )}
            {interimTranscript && (
              <span className="interim">{interimTranscript}</span>
            )}
          </>
        )}
      </div>
      {(finalTranscript || interimTranscript) && (
        <p className="transcript-legend">
          <mark className="filler-mark">amber</mark> = filler word ·{" "}
          <mark className="impact-mark">green</mark> = quantified impact
        </p>
      )}
      {notice && (
        <div className="recorder-notice" role="alert">
          {notice}
        </div>
      )}
      <div className="actions-row">
        <span className="spacer"></span>
        <button className="btn danger ghost" onClick={onEndSession} disabled={endDisabled}>
          End session
        </button>
      </div>
    </div>
  );
}
