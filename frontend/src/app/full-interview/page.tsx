"use client";

/**
 * PrepPilot — Full Interview mode: a hands-free, natural back-and-forth.
 * The interviewer speaks, the mic opens automatically, silence ends the
 * turn server-side (2500ms patience — see set_options), a short spoken
 * acknowledgment plays immediately, then the next question. No buttons
 * needed in the happy path; a "Pause" and "End interview" escape hatch
 * always stay available, and clicking the orb while listening force-ends
 * the turn early (same server call as the practice tab's Done button).
 *
 * Shares the socket manager (lib/ws.ts), audio pipeline (lib/audioCapture.ts)
 * and report view with the practice tab (/interview) — only the turn-taking
 * and the conversational UI differ.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiPost } from "@/lib/api";
import { createInterviewSocket, type ConnectionState, type SocketManager } from "@/lib/ws";
import { useAudioCapture } from "@/lib/audioCapture";
import { useHealth } from "@/lib/health";
import type {
  DeliveryMetrics,
  FeedbackResult,
  PreviousAttempt,
  ReportResult,
  Seniority,
  ServerMessage,
  SessionCreateRequest,
} from "@/lib/types";
import VoiceOrb, { type OrbState } from "@/components/VoiceOrb";
import TranscriptText from "@/components/TranscriptText";
import ConnectionBanner from "@/components/ConnectionBanner";
import SystemBanner from "@/components/SystemBanner";
import ReportView from "@/components/ReportView";
import { ToastHost, useToasts } from "@/components/Toasts";

type Phase = "setup" | "interview" | "report";

interface ConvoEntry {
  id: number;
  role: "interviewer" | "candidate";
  text: string;
  feedback?: FeedbackResult | null;
  metrics?: DeliveryMetrics | null;
  previousAttempt?: PreviousAttempt | null;
  questionId?: number | null;
  modelAnswer?: string | null;
  modelAnswerLoading?: boolean;
}

const VALID_SENIORITY: Seniority[] = ["junior", "mid", "senior", "staff"];
const AUTO_LISTEN_DELAY_MS = 1500; // when TTS is unavailable, read time before the mic opens
const FOCUS_OPTIONS: { value: string; label: string }[] = [
  { value: "behavioral", label: "Behavioral" },
  { value: "system_design", label: "System design" },
  { value: "technical_concept", label: "Technical concepts" },
];

export default function FullInterviewPage() {
  return (
    <Suspense fallback={null}>
      <FullInterviewInner />
    </Suspense>
  );
}

function FullInterviewInner() {
  const { toasts, toast, dismiss } = useToasts();
  const { health } = useHealth();
  const searchParams = useSearchParams();

  const initialRole = searchParams.get("role") || "Software Engineer";
  const seniorityParam = searchParams.get("seniority");
  const initialSeniority = VALID_SENIORITY.includes(seniorityParam as Seniority)
    ? (seniorityParam as Seniority)
    : "mid";
  const questionsParam = parseInt(searchParams.get("questions") || "", 10);
  const initialQuestions =
    Number.isFinite(questionsParam) && questionsParam >= 1 && questionsParam <= 12
      ? questionsParam
      : 5;
  const bankIdsParam = searchParams.get("bank_ids");
  const bankIds = bankIdsParam
    ? bankIdsParam.split(",").map((s) => parseInt(s, 10)).filter((n) => Number.isFinite(n))
    : null;
  const focusParam = searchParams.get("focus");
  const initialFocus = focusParam
    ? focusParam.split(",").filter((f) => FOCUS_OPTIONS.some((o) => o.value === f))
    : FOCUS_OPTIONS.map((o) => o.value);

  const voiceUnavailable =
    !!health?.flags?.stt_missing || !!health?.flags?.vad_missing || health?.stt_backend === "none";

  const [phase, setPhase] = useState<Phase>("setup");
  const [role, setRole] = useState(initialRole);
  const [seniority, setSeniority] = useState<Seniority>(initialSeniority);
  const [numQuestions, setNumQuestions] = useState(String(initialQuestions));
  const [focus, setFocus] = useState<string[]>(initialFocus);
  const [starting, setStarting] = useState(false);

  const [orbState, setOrbState] = useState<OrbState>("idle");
  const [paused, setPaused] = useState(false);
  const [convo, setConvo] = useState<ConvoEntry[]>([]);
  const [qNum, setQNum] = useState(0);
  const [maxQuestions, setMaxQuestions] = useState(0);
  const [report, setReport] = useState<ReportResult | null>(null);
  const [connState, setConnState] = useState<ConnectionState>("connecting");
  const [connAttempt, setConnAttempt] = useState<number | undefined>(undefined);

  const socketRef = useRef<SocketManager | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const convoIdRef = useRef(1);
  const pendingMetricsRef = useRef<DeliveryMetrics | null>(null);
  const pausedRef = useRef(false);
  const autoListenTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const audioCapture = useAudioCapture({
    onFrame: (buf) => socketRef.current?.sendBinary(buf),
  });

  const clearAutoListenTimer = useCallback(() => {
    if (autoListenTimerRef.current) {
      clearTimeout(autoListenTimerRef.current);
      autoListenTimerRef.current = null;
    }
  }, []);

  const beginListening = useCallback(() => {
    if (pausedRef.current) {
      setOrbState("idle");
      return;
    }
    audioCapture.startRecording();
    setOrbState("listening");
  }, [audioCapture]);

  /** Play a base64 WAV; on end (or immediately if TTS unavailable), open the mic. */
  const playQuestionAudio = useCallback(
    (b64: string | undefined) => {
      clearAutoListenTimer();
      if (!b64) {
        setOrbState("idle");
        autoListenTimerRef.current = setTimeout(beginListening, AUTO_LISTEN_DELAY_MS);
        return;
      }
      try {
        if (currentAudioRef.current) currentAudioRef.current.pause();
        const audio = new Audio("data:audio/wav;base64," + b64);
        currentAudioRef.current = audio;
        audio.addEventListener("play", () => setOrbState("speaking"));
        audio.addEventListener("ended", beginListening);
        audio.addEventListener("error", beginListening);
        audio.play().catch(() => {
          // Autoplay blocked — fall back to the read-delay path.
          setOrbState("idle");
          autoListenTimerRef.current = setTimeout(beginListening, AUTO_LISTEN_DELAY_MS);
        });
      } catch {
        setOrbState("idle");
        autoListenTimerRef.current = setTimeout(beginListening, AUTO_LISTEN_DELAY_MS);
      }
    },
    [beginListening, clearAutoListenTimer],
  );

  const playAckAudio = useCallback((b64: string) => {
    try {
      const audio = new Audio("data:audio/wav;base64," + b64);
      audio.play().catch(() => {});
    } catch {
      /* non-fatal — ack is a nicety, not required */
    }
  }, []);

  const handleServerMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "resumed":
          toast(`Reconnected — resuming after question ${msg.answered_count ?? 0}.`, "success", 6000);
          break;
        case "question": {
          const nextNum = typeof msg.order_idx === "number" ? msg.order_idx + 1 : qNum + 1;
          setQNum(nextNum);
          // Server-authoritative — Drill mode overrides the client's guess
          // (see backend/schemas.py WS protocol comment on "question").
          if (typeof msg.max_questions === "number") setMaxQuestions(msg.max_questions);
          setConvo((prev) => [
            ...prev,
            { id: convoIdRef.current++, role: "interviewer", text: msg.text || "" },
          ]);
          playQuestionAudio(msg.audio_b64);
          break;
        }
        case "ack":
          setOrbState("thinking");
          if (msg.audio_b64) playAckAudio(msg.audio_b64);
          break;
        case "transcript_final": {
          audioCapture.stopRecording();
          clearAutoListenTimer();
          setOrbState("thinking");
          const text = msg.text || "";
          setConvo((prev) => [...prev, { id: convoIdRef.current++, role: "candidate", text }]);
          break;
        }
        case "metrics": {
          pendingMetricsRef.current = msg.metrics || (msg as unknown as DeliveryMetrics);
          break;
        }
        case "feedback": {
          const fb = msg.FeedbackResult || msg.feedback || (msg as unknown as FeedbackResult);
          const metrics = pendingMetricsRef.current;
          pendingMetricsRef.current = null;
          setConvo((prev) => {
            const next = [...prev];
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].role === "candidate" && !next[i].feedback) {
                next[i] = {
                  ...next[i],
                  feedback: fb,
                  metrics,
                  previousAttempt: msg.previous_attempt ?? null,
                  questionId: typeof msg.question_id === "number" ? msg.question_id : null,
                };
                break;
              }
            }
            return next;
          });
          break;
        }
        case "model_answer": {
          const qid = msg.question_id;
          const text = msg.text || "";
          setConvo((prev) =>
            prev.map((c) =>
              c.questionId === qid ? { ...c, modelAnswer: text, modelAnswerLoading: false } : c,
            ),
          );
          break;
        }
        case "report": {
          const r = msg.ReportResult || msg.report || (msg as unknown as ReportResult);
          setReport(r);
          setPhase("report");
          setOrbState("idle");
          audioCapture.dispose();
          socketRef.current?.stop();
          break;
        }
        case "status":
          // Full Interview drives its own orb state from question/ack/transcript
          // messages instead of the raw status stream (it needs to be
          // speaking/listening/thinking, not the practice tab's finer states).
          break;
        case "error":
          if (msg.code === "empty_transcript") {
            toast(msg.message || "No speech recognized — please try again.", "info", 5000);
            // Re-open the mic for another attempt at the same question.
            beginListening();
            break;
          }
          toast(msg.message || "Unknown server error");
          break;
        default:
          break;
      }
    },
    [qNum, playQuestionAudio, playAckAudio, audioCapture, clearAutoListenTimer, beginListening, toast],
  );

  const openSocket = useCallback(
    (sessionId: number) => {
      socketRef.current = createInterviewSocket(sessionId, {
        onMessage: handleServerMessage,
        onStateChange: (s, attempt) => {
          setConnState(s);
          setConnAttempt(attempt);
          if (s === "reconnecting") {
            audioCapture.stopRecording();
            clearAutoListenTimer();
          }
          if (s === "open") {
            // Hands-free: server ends the turn itself after 2.5s of silence.
            socketRef.current?.sendJson({
              type: "set_options",
              auto_end_turn: true,
              end_of_turn_silence_ms: 2500,
            });
          }
        },
      });
    },
    [handleServerMessage, audioCapture, clearAutoListenTimer],
  );

  const begin = useCallback(async () => {
    setStarting(true);
    try {
      await audioCapture.init();
    } catch (err) {
      toast(
        "Microphone unavailable — Full Interview needs voice. " +
          (err instanceof Error ? err.message : String(err)),
      );
      setStarting(false);
      return;
    }
    try {
      const req: SessionCreateRequest = {
        role: role.trim() || "Software Engineer",
        seniority,
        jd_text: "",
        focus_areas: focus.length > 0 ? focus : FOCUS_OPTIONS.map((o) => o.value),
        max_questions: bankIds ? bankIds.length : parseInt(numQuestions, 10) || 5,
        mode: "full",
        bank_ids: bankIds,
      };
      const session = await apiPost<{ id: number }>("/api/sessions", req);
      setMaxQuestions(req.max_questions || 0);
      setPhase("interview");
      openSocket(session.id);
    } catch (err) {
      toast("Could not start the session: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setStarting(false);
    }
  }, [audioCapture, role, seniority, numQuestions, focus, bankIds, openSocket, toast]);

  function toggleFocus(value: string, checked: boolean) {
    setFocus((prev) => (checked ? [...prev, value] : prev.filter((v) => v !== value)));
  }

  const requestModelAnswer = useCallback((questionId: number) => {
    setConvo((prev) =>
      prev.map((c) => (c.questionId === questionId ? { ...c, modelAnswerLoading: true } : c)),
    );
    socketRef.current?.sendJson({ type: "model_answer", question_id: questionId });
  }, []);

  const orbClick = useCallback(() => {
    if (orbState !== "listening") return;
    audioCapture.stopRecording();
    clearAutoListenTimer();
    socketRef.current?.sendJson({ type: "end_turn" });
    setOrbState("thinking");
  }, [orbState, audioCapture, clearAutoListenTimer]);

  const togglePause = useCallback(() => {
    setPaused((p) => {
      const next = !p;
      if (!next && orbState === "idle") {
        // Resuming from a paused idle state — pick the mic back up.
        beginListening();
      }
      return next;
    });
  }, [orbState, beginListening]);

  const endInterview = useCallback(() => {
    audioCapture.stopRecording();
    clearAutoListenTimer();
    socketRef.current?.sendJson({ type: "end_session" });
    setOrbState("thinking");
  }, [audioCapture, clearAutoListenTimer]);

  const startNewSession = useCallback(() => {
    socketRef.current?.stop();
    socketRef.current = null;
    audioCapture.dispose();
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    convoIdRef.current = 1;
    setPhase("setup");
    setOrbState("idle");
    setPaused(false);
    setConvo([]);
    setQNum(0);
    setMaxQuestions(0);
    setReport(null);
    setConnState("connecting");
    setConnAttempt(undefined);
  }, [audioCapture]);

  useEffect(() => {
    return () => {
      socketRef.current?.stop();
      audioCapture.dispose();
      clearAutoListenTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const exprValues = convo
    .map((c) => c.metrics?.expressiveness)
    .filter((v): v is number => typeof v === "number" && v > 0);
  const avgExpressiveness =
    exprValues.length > 0 ? exprValues.reduce((a, b) => a + b, 0) / exprValues.length : null;

  return (
    <>
      {phase === "setup" && (
        <>
          <SystemBanner mode="voice" />
          <section className="card">
            <h2>Full Interview</h2>
            <p className="subtitle">
              A hands-free mock interview — the coach speaks each question, listens for your
              answer, and moves on by itself. Just talk.
            </p>
            {voiceUnavailable ? (
              <div className="error-card">
                <div>Full Interview needs voice — speech recognition isn&rsquo;t loaded in this
                  server process. Launch with run.ps1/start.ps1, or use the regular Interview tab
                  in text mode.</div>
              </div>
            ) : (
              <>
                <div className="form-grid">
                  <div>
                    <label className="field-label" htmlFor="fiRole">Role</label>
                    <input
                      id="fiRole"
                      type="text"
                      value={role}
                      onChange={(e) => setRole(e.target.value)}
                      placeholder="e.g. Backend Engineer"
                    />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="fiSeniority">Seniority</label>
                    <select
                      id="fiSeniority"
                      value={seniority}
                      onChange={(e) => setSeniority(e.target.value as Seniority)}
                    >
                      <option value="junior">Junior</option>
                      <option value="mid">Mid</option>
                      <option value="senior">Senior</option>
                      <option value="staff">Staff</option>
                    </select>
                  </div>
                  {!bankIds && (
                    <div>
                      <label className="field-label" htmlFor="fiCount">Number of questions</label>
                      <input
                        id="fiCount"
                        type="number"
                        min={1}
                        max={12}
                        value={numQuestions}
                        onChange={(e) => setNumQuestions(e.target.value)}
                      />
                    </div>
                  )}
                  {!bankIds && (
                    <div className="full">
                      <span className="field-label">Focus areas</span>
                      <div className="checkbox-row">
                        {FOCUS_OPTIONS.map((opt) => (
                          <label className="check-chip" key={opt.value}>
                            <input
                              type="checkbox"
                              checked={focus.includes(opt.value)}
                              onChange={(e) => toggleFocus(opt.value, e.target.checked)}
                            />{" "}
                            {opt.label}
                          </label>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                {bankIds && (
                  <p className="hint-text">Practicing {bankIds.length} question(s) from the question bank.</p>
                )}
                <div className="actions-row">
                  <button className="btn primary lg" onClick={begin} disabled={starting}>
                    {starting ? "Preparing…" : "Begin"}
                  </button>
                </div>
              </>
            )}
          </section>
        </>
      )}

      {phase === "interview" && (
        <section>
          <SystemBanner mode="voice" />
          <ConnectionBanner state={connState} attempt={connAttempt} onRetry={() => socketRef.current?.retryNow()} />

          <div className="full-interview-stage">
            {maxQuestions > 0 && (
              <p className="orb-status-text" style={{ marginTop: 0 }}>
                Question {Math.max(1, qNum)} of {maxQuestions}
              </p>
            )}
            <VoiceOrb state={paused ? "idle" : orbState} meterLevelRef={audioCapture.meterLevelRef} onClick={orbClick} />
            <p className="orb-status-text">
              {paused
                ? "Paused — tap Resume to continue"
                : orbState === "speaking"
                  ? "Interviewer speaking…"
                  : orbState === "listening"
                    ? "Listening — tap the orb to finish early"
                    : orbState === "thinking"
                      ? "Thinking…"
                      : "One moment…"}
            </p>
            <div className="full-interview-controls">
              <button className="btn" onClick={togglePause}>
                {paused ? "Resume" : "Pause"}
              </button>
              <button className="btn danger" onClick={endInterview}>
                End interview
              </button>
            </div>
          </div>

          {convo.some((c) => c.role === "candidate") && (
            <p className="transcript-legend">
              <mark className="filler-mark">amber</mark> = filler word ·{" "}
              <mark className="impact-mark">green</mark> = quantified impact
            </p>
          )}
          <div className="convo">
            {convo.map((c) => (
              <div className={"bubble" + (c.role === "candidate" ? " me" : "")} key={c.id}>
                <div className="meta">{c.role === "candidate" ? "You" : "Interviewer"}</div>
                <div>
                  <TranscriptText text={c.text} />
                </div>
                {c.feedback && (
                  <details>
                    <summary>
                      View coaching (overall {c.feedback.scores.overall}/10)
                      {c.previousAttempt && (
                        <>
                          {" — "}
                          {c.feedback.scores.overall > c.previousAttempt.overall
                            ? `▲ ${c.feedback.scores.overall - c.previousAttempt.overall}`
                            : c.feedback.scores.overall < c.previousAttempt.overall
                              ? `▼ ${c.previousAttempt.overall - c.feedback.scores.overall}`
                              : "= same"}{" "}
                          vs last attempt
                        </>
                      )}
                    </summary>
                    <ul className="plain-list">
                      {c.feedback.strengths.slice(0, 2).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                    <p className="coaching-text">{c.feedback.coaching_summary}</p>
                    {c.questionId != null && (
                      <details className="model-answer-disclosure">
                        <summary
                          onClick={() => {
                            if (!c.modelAnswer && !c.modelAnswerLoading) requestModelAnswer(c.questionId as number);
                          }}
                        >
                          {c.modelAnswerLoading ? "Rewriting your answer…" : "Show how I'd answer this"}
                        </summary>
                        {c.modelAnswer && <p className="coaching-text model-answer-text">{c.modelAnswer}</p>}
                      </details>
                    )}
                  </details>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {phase === "report" && report && (
        <ReportView report={report} onNewSession={startNewSession} avgExpressiveness={avgExpressiveness} />
      )}

      <ToastHost toasts={toasts} onDismiss={dismiss} />
    </>
  );
}
