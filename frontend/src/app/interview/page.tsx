"use client";

/**
 * PrepPilot — interview page.
 *
 * Flow: setup form -> POST /api/sessions -> WebSocket /ws/session/{id}.
 * Text mode sends {"type":"answer_text"}; voice mode captures mic audio via
 * an AudioWorklet (public/audio-worklet.js, registers 'pcm-capture'),
 * downsamples to 16 kHz mono PCM16 and streams ~200ms binary frames.
 * Server pushes question/transcript/metrics/feedback/report/status/error/
 * resumed messages which drive the UI. The socket itself (including
 * reconnect-with-backoff) is owned by lib/ws.ts — this component only reacts
 * to connection-state changes and parsed messages.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiPost } from "@/lib/api";
import { createInterviewSocket, type ConnectionState, type SocketManager } from "@/lib/ws";
import { useAudioCapture } from "@/lib/audioCapture";
import type {
  DeliveryMetrics,
  FeedbackResult,
  PreviousAttempt,
  QuestionCategory,
  ReportResult,
  Seniority,
  ServerMessage,
  SessionCreateRequest,
  SessionSummary,
} from "@/lib/types";
import SetupForm, { type AnswerMode } from "@/components/SetupForm";
import StatusStrip from "@/components/StatusStrip";
import ConnectionBanner from "@/components/ConnectionBanner";
import SystemBanner from "@/components/SystemBanner";
import QuestionCard from "@/components/QuestionCard";
import Recorder from "@/components/Recorder";
import AnswerTimer from "@/components/AnswerTimer";
import FeedbackCard from "@/components/FeedbackCard";
import ReportView from "@/components/ReportView";
import MistakeAlerts from "@/components/MistakeAlerts";
import { ToastHost, useToasts } from "@/components/Toasts";
import { useHealth } from "@/lib/health";

type Phase = "setup" | "interview" | "report";

interface CurrentQuestion {
  text: string;
  category: QuestionCategory;
  isFollowup: boolean;
  audioB64: string | null;
  bookmarked: boolean;
}

interface FeedbackEntry {
  id: number;
  qNum: number;
  questionId: number | null;
  feedback: FeedbackResult;
  metrics: DeliveryMetrics | null;
  previousAttempt: PreviousAttempt | null;
  modelAnswer?: string | null;
  modelAnswerLoading?: boolean;
}

const INITIAL_STATE = {
  phase: "setup" as Phase,
  mode: "text" as AnswerMode,
  status: { state: "thinking", detail: "Connecting…" } as { state: string; detail?: string },
  listening: false,
  qNum: 0,
  maxQuestions: 0,
  question: null as CurrentQuestion | null,
  feedbackCards: [] as FeedbackEntry[],
  report: null as ReportResult | null,
};

const VALID_SENIORITY: Seniority[] = ["junior", "mid", "senior", "staff"];
const VALID_FOCUS = ["behavioral", "system_design", "technical_concept"];

// useSearchParams requires a Suspense boundary in a static export, or the
// build fails. The default export supplies it; all logic lives in Inner.
export default function InterviewPage() {
  return (
    <Suspense fallback={null}>
      <InterviewPageInner />
    </Suspense>
  );
}

function InterviewPageInner() {
  const { toasts, toast, dismiss } = useToasts();
  const { health } = useHealth();
  const searchParams = useSearchParams();

  // Prefill the setup form from query params (e.g. from the question-bank
  // "Practice this set" CTA or the Home quick-start card). Parsed once.
  const initialRole = searchParams.get("role") || undefined;
  const seniorityParam = searchParams.get("seniority");
  const initialSeniority = VALID_SENIORITY.includes(seniorityParam as Seniority)
    ? (seniorityParam as Seniority)
    : undefined;
  const questionsParam = parseInt(searchParams.get("questions") || "", 10);
  const initialNumQuestions =
    Number.isFinite(questionsParam) && questionsParam >= 1 && questionsParam <= 12
      ? questionsParam
      : undefined;
  const focusParam = searchParams.get("focus");
  const initialFocus = focusParam
    ? focusParam.split(",").filter((f) => VALID_FOCUS.includes(f))
    : undefined;
  const modeParam = searchParams.get("mode");
  const initialSessionMode = modeParam === "drill" ? "drill" : undefined;
  const bankIdsParam = searchParams.get("bank_ids");
  const initialBankIds = bankIdsParam
    ? bankIdsParam
        .split(",")
        .map((s) => parseInt(s, 10))
        .filter((n) => Number.isFinite(n) && n > 0)
    : undefined;
  // Only hard-disable voice when the config explicitly turns STT off. When
  // the package probe fails we keep voice SELECTABLE (the SystemBanner warns)
  // rather than blocking it — being locked out entirely is worse than a
  // warning, and the probe can be wrong across processes.
  const voiceDisabled = health?.stt_backend === "none";
  const voiceDisabledReason = voiceDisabled
    ? "Voice mode is turned off in config (stt.backend: none). Answer in text mode."
    : undefined;

  // ---------------------------------------------------------------- state
  const [phase, setPhase] = useState<Phase>(INITIAL_STATE.phase);
  const [mode, setMode] = useState<AnswerMode>(INITIAL_STATE.mode);
  const [starting, setStarting] = useState(false);
  const [status, setStatus] = useState(INITIAL_STATE.status);
  const [listening, setListening] = useState(INITIAL_STATE.listening);
  const [qNum, setQNum] = useState(INITIAL_STATE.qNum);
  const [maxQuestions, setMaxQuestions] = useState(INITIAL_STATE.maxQuestions);
  const [question, setQuestion] = useState<CurrentQuestion | null>(INITIAL_STATE.question);
  const [sessionRole, setSessionRole] = useState("Software Engineer");
  const [sessionSeniority, setSessionSeniority] = useState<Seniority>("mid");
  const [rapidRound, setRapidRound] = useState(false);
  // Manual advance (practice mode): after feedback, the server waits and the
  // user picks "Try again" or "Next question". null = not awaiting.
  const [awaitAction, setAwaitAction] = useState<null | { sessionComplete: boolean }>(null);
  const [answerText, setAnswerText] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [recorderNotice, setRecorderNotice] = useState<string | null>(null);
  const [liveMetrics, setLiveMetrics] = useState<DeliveryMetrics | null>(null);
  const [feedbackCards, setFeedbackCards] = useState<FeedbackEntry[]>(INITIAL_STATE.feedbackCards);
  const [report, setReport] = useState<ReportResult | null>(INITIAL_STATE.report);
  const [connState, setConnState] = useState<ConnectionState>("connecting");
  const [connAttempt, setConnAttempt] = useState<number | undefined>(undefined);
  const [speaking, setSpeaking] = useState(false);

  // ---------------------------------------------------------------- refs
  const socketRef = useRef<SocketManager | null>(null);
  const pendingMetricsRef = useRef<DeliveryMetrics | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const qNumRef = useRef(0);
  const phaseRef = useRef<Phase>("setup");
  const cardIdRef = useRef(1);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // ---------------------------------------------------------------- ws send

  const wsSendJson = useCallback((obj: Record<string, unknown>) => {
    socketRef.current?.sendJson(obj);
  }, []);

  // ---------------------------------------------------------------- audio

  const audioCapture = useAudioCapture({
    onFrame: (buf) => socketRef.current?.sendBinary(buf),
  });
  const { meterLevelRef } = audioCapture;

  const startRecording = useCallback(() => {
    audioCapture.startRecording();
    setFinalTranscript("");
    setInterimTranscript("");
    setRecorderNotice(null);
  }, [audioCapture]);

  const doneAnswering = useCallback(() => {
    audioCapture.stopRecording();
    wsSendJson({ type: "end_turn" });
  }, [audioCapture, wsSendJson]);

  // ---------------------------------------------------------------- playback

  /** Play a base64-encoded WAV via an Audio element (data URL). */
  const playWavB64 = useCallback((b64: string) => {
    try {
      if (currentAudioRef.current) currentAudioRef.current.pause();
      const audio = new Audio("data:audio/wav;base64," + b64);
      currentAudioRef.current = audio;
      audio.addEventListener("play", () => setSpeaking(true));
      audio.addEventListener("ended", () => setSpeaking(false));
      audio.addEventListener("pause", () => setSpeaking(false));
      audio.play().catch(() => {
        /* autoplay blocked — question text is visible anyway */
      });
    } catch {
      /* malformed audio — ignore, text is shown */
    }
  }, []);

  const replayQuestionAudio = useCallback(() => {
    if (question?.audioB64) playWavB64(question.audioB64);
  }, [question, playWavB64]);

  const requestModelAnswer = useCallback(
    (questionId: number) => {
      setFeedbackCards((prev) =>
        prev.map((c) => (c.questionId === questionId ? { ...c, modelAnswerLoading: true } : c)),
      );
      wsSendJson({ type: "model_answer", question_id: questionId });
    },
    [wsSendJson],
  );

  const bookmarkQuestion = useCallback(async () => {
    if (!question || question.bookmarked) return;
    try {
      await apiPost<{ id: number }>("/api/question-bank/adopt", {
        text: question.text,
        category: question.category,
        role: sessionRole,
        seniority: sessionSeniority,
      });
      setQuestion((q) => (q ? { ...q, bookmarked: true } : q));
      toast("Saved — find it in the Question bank to drill later.", "success", 4000);
    } catch (err) {
      toast("Could not save the question: " + (err instanceof Error ? err.message : String(err)));
    }
  }, [question, sessionRole, sessionSeniority, toast]);

  // ---------------------------------------------------------------- server messages

  const handleServerMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "resumed":
          toast(
            `Reconnected — resuming after question ${msg.answered_count ?? 0}.`,
            "success",
            6000,
          );
          break;
        case "question": {
          const nextNum =
            typeof msg.order_idx === "number"
              ? msg.order_idx + 1
              : qNumRef.current + 1;
          qNumRef.current = nextNum;
          setQNum(nextNum);
          // Server-authoritative — Drill mode overrides the client's guess
          // (see backend/schemas.py WS protocol comment on "question").
          if (typeof msg.max_questions === "number") setMaxQuestions(msg.max_questions);
          setQuestion({
            text: msg.text || "",
            category: msg.category || "behavioral",
            isFollowup: !!msg.is_followup,
            audioB64: msg.audio_b64 || null,
            bookmarked: false,
          });
          // Reset answer inputs for the new turn.
          setAwaitAction(null);
          setAnswerText("");
          setFinalTranscript("");
          setInterimTranscript("");
          setRecorderNotice(null);
          setLiveMetrics(null);
          if (msg.audio_b64) playWavB64(msg.audio_b64);
          break;
        }
        case "await_action":
          // Practice mode: feedback is in; wait for Try again / Next question.
          setAwaitAction({ sessionComplete: !!msg.session_complete });
          setListening(false);
          setStatus({ state: "done", detail: undefined });
          break;
        case "transcript_interim":
          setInterimTranscript(msg.text || "");
          break;
        case "transcript_final": {
          const text = msg.text || "";
          setFinalTranscript((prev) => (prev ? prev + " " + text : text));
          setInterimTranscript("");
          break;
        }
        case "metrics": {
          const parsed = msg.metrics || (msg as unknown as DeliveryMetrics);
          pendingMetricsRef.current = parsed;
          setLiveMetrics(parsed);
          break;
        }
        case "feedback": {
          // Tolerate payload shapes.
          const fb =
            msg.FeedbackResult ||
            msg.feedback ||
            (msg as unknown as FeedbackResult);
          const metrics = pendingMetricsRef.current;
          pendingMetricsRef.current = null;
          setFeedbackCards((prev) => [
            {
              id: cardIdRef.current++,
              qNum: qNumRef.current,
              questionId: typeof msg.question_id === "number" ? msg.question_id : null,
              feedback: fb,
              metrics,
              previousAttempt: msg.previous_attempt ?? null,
            },
            ...prev,
          ]);
          break;
        }
        case "model_answer": {
          const qid = msg.question_id;
          const text = msg.text || "";
          setFeedbackCards((prev) =>
            prev.map((c) =>
              c.questionId === qid ? { ...c, modelAnswer: text, modelAnswerLoading: false } : c,
            ),
          );
          break;
        }
        case "report": {
          const r =
            msg.ReportResult || msg.report || (msg as unknown as ReportResult);
          setReport(r);
          setPhase("report");
          setStatus({ state: "done" });
          audioCapture.dispose();
          socketRef.current?.stop();
          break;
        }
        case "status": {
          const state = msg.state || "thinking";
          setStatus({ state, detail: msg.detail });
          setListening(state === "listening");
          break;
        }
        case "error":
          if (msg.code === "empty_transcript") {
            // Inline, non-toast: the user should just try again on the same
            // question, not treat this like a fatal error.
            setRecorderNotice(msg.message || "No speech recognized — please try again.");
            break;
          }
          toast(msg.message || "Unknown server error");
          break;
        default:
          break; // ignore unknown message types
      }
    },
    [playWavB64, audioCapture, toast],
  );

  const openSocket = useCallback(
    (sessionId: number) => {
      socketRef.current = createInterviewSocket(sessionId, {
        onMessage: handleServerMessage,
        onStateChange: (s, attempt) => {
          setConnState(s);
          setConnAttempt(attempt);
          if (s === "reconnecting") {
            // A reconnect attempt mid-turn can't recover an in-flight
            // recording — the VAD/turn state on the server is per-connection.
            // stopRecording() is a no-op if nothing was recording.
            audioCapture.stopRecording();
          }
          if (s === "open") {
            // Practice tab: never auto-end the turn on silence — a thinking
            // pause used to get scored as "done answering". Only the Done
            // button (end_turn) ends a turn here. manual_advance keeps the
            // server from jumping to the next question after feedback, so the
            // user can retry. Re-sent on every (re)connect since the server
            // rebuilds this state fresh.
            socketRef.current?.sendJson({
              type: "set_options",
              auto_end_turn: false,
              manual_advance: true,
            });
          }
        },
      });
    },
    [handleServerMessage, audioCapture],
  );

  // ---------------------------------------------------------------- actions

  const startInterview = useCallback(
    async (req: SessionCreateRequest, requestedMode: AnswerMode, rapidRound: boolean) => {
      setStarting(true);
      setSessionRole(req.role);
      setSessionSeniority(req.seniority);
      setRapidRound(rapidRound);
      try {
        const session = await apiPost<SessionSummary>("/api/sessions", req);

        // In voice mode, get the microphone ready before the first question.
        let effectiveMode = requestedMode;
        if (requestedMode === "voice") {
          try {
            await audioCapture.init();
          } catch (err) {
            toast(
              "Microphone unavailable — falling back to text mode. " +
                (err instanceof Error ? err.message : String(err)),
            );
            effectiveMode = "text";
          }
        }

        setMode(effectiveMode);
        setMaxQuestions(req.max_questions || 0);
        setPhase("interview");
        openSocket(session.id);
      } catch (err) {
        toast(
          "Could not start the session: " +
            (err instanceof Error ? err.message : String(err)),
        );
      } finally {
        setStarting(false);
      }
    },
    [audioCapture, openSocket, toast],
  );

  const submitTextAnswer = useCallback(() => {
    const text = answerText.trim();
    if (!text) {
      toast("Type an answer first.", "info", 4000);
      return;
    }
    wsSendJson({ type: "answer_text", text });
    setAnswerText("");
    setListening(false);
  }, [answerText, toast, wsSendJson]);

  const retryQuestion = useCallback(() => {
    setAwaitAction(null);
    setAnswerText("");
    setFinalTranscript("");
    setInterimTranscript("");
    setLiveMetrics(null);
    wsSendJson({ type: "retry_question" });
  }, [wsSendJson]);

  const rephraseQuestion = useCallback(() => {
    setAwaitAction(null);
    setAnswerText("");
    setFinalTranscript("");
    setInterimTranscript("");
    setLiveMetrics(null);
    setStatus({ state: "thinking", detail: "rephrasing the question…" });
    wsSendJson({ type: "rephrase_question" });
  }, [wsSendJson]);

  // Switch answer modality mid-session (fixes the "picked the wrong mode" or
  // "mic died / room got noisy" dead-end). No server change needed — the WS
  // handles answer_text and audio frames per-message. Clears any in-progress
  // answer so the new modality starts clean.
  const switchAnswerMode = useCallback(
    async (target: AnswerMode) => {
      if (target === mode) return;
      if (target === "voice") {
        if (voiceDisabled) {
          toast(voiceDisabledReason || "Voice mode is unavailable.", "info", 5000);
          return;
        }
        try {
          await audioCapture.init();
        } catch (err) {
          toast(
            "Microphone unavailable — staying in text mode. " +
              (err instanceof Error ? err.message : String(err)),
          );
          return;
        }
      } else {
        audioCapture.stopRecording();
      }
      setMode(target);
      setAnswerText("");
      setFinalTranscript("");
      setInterimTranscript("");
      setRecorderNotice(null);
    },
    [mode, voiceDisabled, voiceDisabledReason, audioCapture, toast],
  );

  const nextQuestion = useCallback(() => {
    setAwaitAction(null);
    wsSendJson({ type: "next_question" });
  }, [wsSendJson]);

  // Rapid Round: 90s per answer, auto-advances instead of waiting on the
  // candidate. Text mode submits whatever's typed (silently skips if blank —
  // the round keeps moving rather than nagging); voice mode ends the turn
  // exactly like the Done button.
  const autoAdvanceAnswer = useCallback(() => {
    if (mode === "text") {
      if (answerText.trim()) submitTextAnswer();
    } else if (audioCapture.recording) {
      doneAnswering();
    }
  }, [mode, answerText, submitTextAnswer, audioCapture, doneAnswering]);

  const endSession = useCallback(() => {
    wsSendJson({ type: "end_session" });
    setStatus({ state: "thinking", detail: "Generating your session report…" });
    audioCapture.stopRecording();
  }, [audioCapture, wsSendJson]);

  const retryConnection = useCallback(() => {
    socketRef.current?.retryNow();
  }, []);

  /** Full reset back to the setup form — no page reload, so nothing else
   * (e.g. an open toast) has to survive a hard navigation. */
  const startNewSession = useCallback(() => {
    socketRef.current?.stop();
    socketRef.current = null;
    audioCapture.dispose();
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    qNumRef.current = 0;
    cardIdRef.current = 1;
    setPhase(INITIAL_STATE.phase);
    setMode(INITIAL_STATE.mode);
    setStatus(INITIAL_STATE.status);
    setListening(INITIAL_STATE.listening);
    setQNum(INITIAL_STATE.qNum);
    setMaxQuestions(INITIAL_STATE.maxQuestions);
    setQuestion(INITIAL_STATE.question);
    setAnswerText("");
    setFinalTranscript("");
    setInterimTranscript("");
    setRecorderNotice(null);
    setLiveMetrics(null);
    setFeedbackCards(INITIAL_STATE.feedbackCards);
    setReport(INITIAL_STATE.report);
    setConnState("connecting");
    setConnAttempt(undefined);
    setSpeaking(false);
    setRapidRound(false);
    setAwaitAction(null);
  }, [audioCapture]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      socketRef.current?.stop();
      audioCapture.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------- render

  const connectionBusy = connState === "reconnecting" || connState === "disconnected";

  // Session-average expressiveness for the report tile — only from voice
  // answers (text answers have expressiveness 0 and aren't meaningful here).
  const exprValues = feedbackCards
    .map((c) => c.metrics?.expressiveness)
    .filter((v): v is number => typeof v === "number" && v > 0);
  const avgExpressiveness =
    exprValues.length > 0
      ? exprValues.reduce((a, b) => a + b, 0) / exprValues.length
      : null;

  return (
    <>
      {phase === "setup" && (
        <>
          <SystemBanner />
          <SetupForm
            onStart={startInterview}
            onError={(m) => toast(m)}
            busy={starting}
            voiceDisabled={voiceDisabled}
            voiceDisabledReason={voiceDisabledReason}
            initialRole={initialRole}
            initialSeniority={initialSeniority}
            initialNumQuestions={initialNumQuestions}
            initialFocus={initialFocus}
            initialSessionMode={initialSessionMode}
            initialBankIds={initialBankIds}
          />
        </>
      )}

      {phase === "interview" && (
        <section>
          <SystemBanner mode={mode} />
          <ConnectionBanner state={connState} attempt={connAttempt} onRetry={retryConnection} />

          <div className="live-grid">
            <div className="live-main">
              <QuestionCard
                qNum={Math.max(1, qNum)}
                maxQuestions={maxQuestions}
                category={question?.category || "behavioral"}
                isFollowup={!!question?.isFollowup}
                text={question?.text || ""}
                canReplay={!!question?.audioB64}
                speaking={speaking}
                onReplay={replayQuestionAudio}
                onBookmark={bookmarkQuestion}
                bookmarked={!!question?.bookmarked}
              />

              {!awaitAction && (
                <div className="mode-switch-row">
                  <span className="mode-switch-label">
                    Answering by {mode === "text" ? "text" : "voice"}
                  </span>
                  <button
                    type="button"
                    className="mode-switch-btn"
                    onClick={() => switchAnswerMode(mode === "text" ? "voice" : "text")}
                    disabled={connectionBusy || (mode === "text" && voiceDisabled)}
                    title={
                      mode === "text" && voiceDisabled
                        ? voiceDisabledReason
                        : `Switch to ${mode === "text" ? "voice" : "text"} answers`
                    }
                  >
                    {mode === "text" ? "🎙 Switch to voice" : "⌨ Switch to text"}
                  </button>
                </div>
              )}

              {awaitAction ? (
                <div className="answer-area card await-action-card">
                  <p className="await-action-title">
                    {awaitAction.sessionComplete
                      ? "That was the last question. Retry it, or wrap up."
                      : "Reviewed. Try this question again, or move on."}
                  </p>
                  <div className="actions-row">
                    <button className="btn" onClick={retryQuestion} disabled={connectionBusy}>
                      ↻ Try again
                    </button>
                    <button
                      className="btn"
                      onClick={rephraseQuestion}
                      disabled={connectionBusy}
                      title="Re-ask this question worded differently — same topic"
                    >
                      🔀 Ask differently
                    </button>
                    <button className="btn primary" onClick={nextQuestion} disabled={connectionBusy}>
                      {awaitAction.sessionComplete ? "See report →" : "Next question →"}
                    </button>
                    <span className="spacer"></span>
                    {!awaitAction.sessionComplete && (
                      <button className="btn danger" onClick={endSession} disabled={connectionBusy}>
                        End session
                      </button>
                    )}
                  </div>
                </div>
              ) : mode === "text" ? (
                <div className="answer-area card">
                  <div className="question-header-row" style={{ marginBottom: 6 }}>
                    <label className="field-label" htmlFor="answerInput" style={{ margin: 0 }}>
                      Your answer
                    </label>
                    <AnswerTimer
                      active={listening}
                      resetKey={qNum}
                      autoSubmitAtSec={rapidRound ? 90 : undefined}
                      onAutoSubmit={autoAdvanceAnswer}
                    />
                  </div>
                  <textarea
                    id="answerInput"
                    value={answerText}
                    placeholder="Type your answer here..."
                    onChange={(e) => setAnswerText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        submitTextAnswer();
                      }
                    }}
                  />
                  <div className="word-count">
                    {answerText.trim() ? answerText.trim().split(/\s+/).length : 0} words
                  </div>
                  <div className="actions-row">
                    <button
                      className="btn primary"
                      onClick={submitTextAnswer}
                      disabled={!listening || connectionBusy}
                    >
                      Submit answer
                    </button>
                    <span className="spacer"></span>
                    <button className="btn danger" onClick={endSession} disabled={connectionBusy}>
                      End session
                    </button>
                  </div>
                </div>
              ) : (
                <Recorder
                  recording={audioCapture.recording}
                  canRecord={listening && !audioCapture.recording && !connectionBusy}
                  finalTranscript={finalTranscript}
                  interimTranscript={interimTranscript}
                  meterLevelRef={meterLevelRef}
                  onStart={startRecording}
                  onDone={doneAnswering}
                  onEndSession={endSession}
                  endDisabled={connectionBusy}
                  notice={recorderNotice}
                  timerSlot={
                    <AnswerTimer
                      active={listening}
                      resetKey={qNum}
                      autoSubmitAtSec={rapidRound ? 90 : undefined}
                      onAutoSubmit={autoAdvanceAnswer}
                    />
                  }
                />
              )}
            </div>

            <aside className="coach-col">
              <StatusStrip state={status.state} detail={status.detail} />
              <MistakeAlerts metrics={liveMetrics} />
              <div className="feedback-stack">
                {feedbackCards.map((c, idx) => (
                  <FeedbackCard
                    key={c.id}
                    qNum={c.qNum}
                    feedback={c.feedback}
                    metrics={c.metrics}
                    isNew={idx === 0}
                    previousAttempt={c.previousAttempt}
                    modelAnswer={c.modelAnswer}
                    modelAnswerLoading={c.modelAnswerLoading}
                    onRequestModelAnswer={
                      c.questionId != null ? () => requestModelAnswer(c.questionId as number) : undefined
                    }
                  />
                ))}
              </div>
            </aside>
          </div>
        </section>
      )}

      {phase === "report" && report && (
        <ReportView
          report={report}
          onNewSession={startNewSession}
          avgExpressiveness={avgExpressiveness}
        />
      )}

      <ToastHost toasts={toasts} onDismiss={dismiss} />
    </>
  );
}
