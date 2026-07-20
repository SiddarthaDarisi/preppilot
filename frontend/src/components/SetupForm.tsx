"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { BankItem, InterviewerPersona, Seniority, SessionCreateRequest, SessionMode } from "@/lib/types";

export type AnswerMode = "text" | "voice";

const FOCUS_OPTIONS: { value: string; label: string; default: boolean }[] = [
  { value: "behavioral", label: "Behavioral", default: true },
  { value: "system_design", label: "System design", default: true },
  { value: "technical_concept", label: "Technical concepts", default: false },
];

export default function SetupForm({
  onStart,
  onError,
  busy,
  voiceDisabled = false,
  voiceDisabledReason,
  initialRole,
  initialSeniority,
  initialNumQuestions,
  initialFocus,
  initialSessionMode,
  initialBankIds,
}: {
  onStart: (req: SessionCreateRequest, mode: AnswerMode, rapidRound: boolean) => void;
  onError: (message: string) => void;
  busy: boolean;
  voiceDisabled?: boolean;
  voiceDisabledReason?: string;
  initialRole?: string;
  initialSeniority?: Seniority;
  initialNumQuestions?: number;
  initialFocus?: string[];
  initialSessionMode?: SessionMode;
  initialBankIds?: number[];
}) {
  const [role, setRole] = useState(initialRole || "Software Engineer");
  const [seniority, setSeniority] = useState<Seniority>(initialSeniority || "mid");
  const [jdText, setJdText] = useState("");
  const [focus, setFocus] = useState<string[]>(
    initialFocus && initialFocus.length > 0
      ? initialFocus
      : FOCUS_OPTIONS.filter((o) => o.default).map((o) => o.value),
  );
  const [numQuestions, setNumQuestions] = useState(
    initialNumQuestions ? String(initialNumQuestions) : "6",
  );
  const [mode, setMode] = useState<AnswerMode>("text");
  const bankIds = initialBankIds && initialBankIds.length > 0 ? initialBankIds : undefined;
  const [sessionMode, setSessionMode] = useState<SessionMode>(
    initialSessionMode === "drill" && bankIds ? "drill" : "adaptive",
  );
  const [persona, setPersona] = useState<InterviewerPersona>("neutral");
  const [rapidRound, setRapidRound] = useState(false);
  // Inline Drill picker: saved bank questions, loaded when Drill is selected
  // without a preselected set from the Question bank page.
  const [bankItems, setBankItems] = useState<BankItem[] | null>(null);
  const [bankLoadFailed, setBankLoadFailed] = useState(false);
  const [pickedIds, setPickedIds] = useState<number[]>([]);

  useEffect(() => {
    if (sessionMode !== "drill" || bankIds || bankItems !== null || bankLoadFailed) return;
    apiGet<{ items: BankItem[] }>("/api/question-bank/items")
      .then((r) => setBankItems(r.items))
      .catch(() => setBankLoadFailed(true));
  }, [sessionMode, bankIds, bankItems, bankLoadFailed]);

  function togglePicked(id: number, checked: boolean) {
    // Array (not Set) so drill order = the order you picked them in.
    setPickedIds((prev) => (checked ? [...prev, id] : prev.filter((p) => p !== id)));
  }

  function toggleFocus(value: string, checked: boolean) {
    setFocus((prev) =>
      checked ? [...prev, value] : prev.filter((v) => v !== value),
    );
  }

  function start() {
    if (sessionMode === "adaptive" && focus.length === 0) {
      onError("Pick at least one focus area.");
      return;
    }
    const drillIds = bankIds ?? (pickedIds.length > 0 ? pickedIds : undefined);
    if (sessionMode === "drill" && !drillIds) {
      onError("Pick at least one question to drill (or generate some in the Question bank first).");
      return;
    }
    onStart(
      {
        role: role.trim() || "Software Engineer",
        seniority,
        jd_text: jdText.trim(),
        // Drill runs an exact set, so focus areas don't apply there.
        focus_areas: sessionMode === "drill" ? [] : focus,
        max_questions: rapidRound ? 6 : parseInt(numQuestions, 10) || 6,
        mode: sessionMode,
        bank_ids: sessionMode === "drill" ? drillIds : undefined,
        persona,
      },
      mode,
      rapidRound,
    );
  }

  return (
    <section className="card">
      <h2>Set up your mock interview</h2>
      <p className="subtitle">Pick a role and how you want to practice.</p>

      <div className="form-grid">
        <div>
          <label className="field-label" htmlFor="roleInput">
            Role
          </label>
          <input
            type="text"
            id="roleInput"
            value={role}
            placeholder="e.g. Backend Engineer"
            onChange={(e) => setRole(e.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="senioritySelect">
            Seniority
          </label>
          <select
            id="senioritySelect"
            value={seniority}
            onChange={(e) => setSeniority(e.target.value as Seniority)}
          >
            <option value="junior">Junior</option>
            <option value="mid">Mid</option>
            <option value="senior">Senior</option>
            <option value="staff">Staff</option>
          </select>
        </div>

        <div>
          <span className="field-label">Answer mode</span>
          <div className="mode-toggle">
            <button
              type="button"
              className={mode === "text" ? "active" : ""}
              onClick={() => setMode("text")}
            >
              Text
            </button>
            <button
              type="button"
              className={mode === "voice" ? "active" : ""}
              onClick={() => setMode("voice")}
              disabled={voiceDisabled}
              title={voiceDisabled ? voiceDisabledReason : undefined}
            >
              Voice
            </button>
          </div>
        </div>
        <div>
          <span className="field-label">Question source</span>
          <div className="mode-toggle">
            <button
              type="button"
              className={sessionMode === "adaptive" ? "active" : ""}
              onClick={() => setSessionMode("adaptive")}
            >
              Adaptive
            </button>
            <button
              type="button"
              className={sessionMode === "drill" ? "active" : ""}
              onClick={() => setSessionMode("drill")}
            >
              Drill
            </button>
          </div>
        </div>

        {/* Adaptive: focus areas + count. Drill: neither applies (exact set). */}
        {sessionMode === "adaptive" && (
          <>
            <div className="full">
              <span className="field-label">Focus areas</span>
              <div className="checkbox-row">
                {FOCUS_OPTIONS.map((opt) => (
                  <label className="check-chip" key={opt.value}>
                    <input
                      type="checkbox"
                      name="focus"
                      value={opt.value}
                      checked={focus.includes(opt.value)}
                      onChange={(e) => toggleFocus(opt.value, e.target.checked)}
                    />{" "}
                    {opt.label}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="field-label" htmlFor="numQuestions">
                Number of questions
              </label>
              <input
                type="number"
                id="numQuestions"
                min={1}
                max={12}
                value={rapidRound ? "6" : numQuestions}
                disabled={rapidRound}
                onChange={(e) => setNumQuestions(e.target.value)}
              />
            </div>
          </>
        )}

        {sessionMode === "drill" && bankIds && (
          <div className="full">
            <p className="hint-text" style={{ margin: 0 }}>
              Drilling {bankIds.length} question{bankIds.length === 1 ? "" : "s"} picked in the
              Question bank.
            </p>
          </div>
        )}

        {sessionMode === "drill" && !bankIds && (
          <div className="full">
            <span className="field-label">
              Pick questions to repeat{pickedIds.length > 0 ? ` — ${pickedIds.length} selected` : ""}
            </span>
            {bankLoadFailed && (
              <p className="hint-text" style={{ margin: 0 }}>
                Could not load your saved questions — is the backend running?
              </p>
            )}
            {bankItems !== null && bankItems.length === 0 && (
              <p className="hint-text" style={{ margin: 0 }}>
                Nothing saved yet. <Link href="/question-bank/">Generate questions</Link> or star a
                question during an interview, then come back to drill it.
              </p>
            )}
            {bankItems === null && !bankLoadFailed && (
              <div className="skeleton skeleton-row" style={{ height: 44 }} />
            )}
            {bankItems !== null && bankItems.length > 0 && (
              <div className="drill-picker">
                {bankItems.map((item) => (
                  <label className="drill-pick-row" key={item.id}>
                    <input
                      type="checkbox"
                      checked={pickedIds.includes(item.id)}
                      onChange={(e) => togglePicked(item.id, e.target.checked)}
                    />
                    <span className={"badge cat-" + item.category}>{humanize(item.category)}</span>
                    <span className="drill-pick-text">{item.text}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Everything most people won't touch, folded away. */}
      <details className="advanced-options">
        <summary>Advanced options</summary>
        <div className="form-grid" style={{ marginTop: 16 }}>
          <div className="full">
            <label className="field-label" htmlFor="jdInput">
              Job description (optional)
            </label>
            <textarea
              id="jdInput"
              value={jdText}
              placeholder="Paste the job description for role-specific questions..."
              onChange={(e) => setJdText(e.target.value)}
            />
          </div>
          <div>
            <span className="field-label">Interviewer persona</span>
            <div className="mode-toggle">
              <button
                type="button"
                className={persona === "neutral" ? "active" : ""}
                onClick={() => setPersona("neutral")}
              >
                Neutral
              </button>
              <button
                type="button"
                className={persona === "friendly" ? "active" : ""}
                onClick={() => setPersona("friendly")}
              >
                Friendly
              </button>
              <button
                type="button"
                className={persona === "tough" ? "active" : ""}
                onClick={() => setPersona("tough")}
              >
                Tough
              </button>
            </div>
          </div>
          <div className="full">
            <label className="check-chip rapid-round-chip">
              <input
                type="checkbox"
                checked={rapidRound}
                onChange={(e) => setRapidRound(e.target.checked)}
              />{" "}
              Rapid Round — 6 quick questions, 90s per answer (auto-advances)
            </label>
          </div>
        </div>
      </details>

      <div className="actions-row">
        <button className="btn primary" onClick={start} disabled={busy}>
          Start interview
        </button>
        <Link href="/full-interview" className="btn">
          Full Interview →
        </Link>
      </div>
    </section>
  );
}
