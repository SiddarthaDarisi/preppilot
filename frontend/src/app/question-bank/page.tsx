"use client";

/**
 * Question bank — generates a tailored study list from a role/JD via
 * POST /api/question-bank (the interviewer generates its own live questions;
 * this is a separate study aid). "Practice this set" hands off to /interview
 * with the role/seniority/focus prefilled via query params.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { apiPost } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { GeneratedQuestion, QuestionBankRequest, QuestionBankResult, Seniority } from "@/lib/types";

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; questions: GeneratedQuestion[] };

export default function QuestionBankPage() {
  const [role, setRole] = useState("Software Engineer");
  const [seniority, setSeniority] = useState<Seniority>("mid");
  const [jdText, setJdText] = useState("");
  const [nBehavioral, setNBehavioral] = useState("4");
  const [nSystem, setNSystem] = useState("2");
  const [nTechnical, setNTechnical] = useState("3");
  const [state, setState] = useState<State>({ status: "idle" });
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [company, setCompany] = useState("");
  const [customText, setCustomText] = useState("");
  const [quickAddBusy, setQuickAddBusy] = useState(false);
  const [quickAddError, setQuickAddError] = useState<string | null>(null);

  /** Merge questions into the list (works from any state, de-dupes by text). */
  function mergeQuestions(incoming: GeneratedQuestion[]) {
    setState((prev) => {
      const existing = prev.status === "ready" ? prev.questions : [];
      const existingTexts = new Set(existing.map((q) => q.text.toLowerCase()));
      const fresh = incoming.filter((q) => !existingTexts.has(q.text.toLowerCase()));
      return { status: "ready", questions: [...existing, ...fresh] };
    });
  }

  async function addHrSet() {
    setQuickAddBusy(true);
    setQuickAddError(null);
    try {
      const data = await apiPost<QuestionBankResult>("/api/question-bank/hr-set", {
        company: company.trim(),
        role: role.trim() || "Software Engineer",
        seniority,
      });
      mergeQuestions(data.questions);
      // Preselect the freshly added set so "Drill N selected" is one click away.
      setSelected((prev) => {
        const next = new Set(prev);
        for (const q of data.questions) if (q.id != null) next.add(q.id);
        return next;
      });
    } catch (err) {
      setQuickAddError(err instanceof Error ? err.message : String(err));
    } finally {
      setQuickAddBusy(false);
    }
  }

  async function addCustomQuestion() {
    const text = customText.trim();
    if (!text) return;
    setQuickAddBusy(true);
    setQuickAddError(null);
    try {
      const { id } = await apiPost<{ id: number }>("/api/question-bank/adopt", {
        text,
        category: "behavioral",
        role: role.trim() || "Software Engineer",
        seniority,
      });
      mergeQuestions([
        { id, text, category: "behavioral", targets_competency: "", difficulty: "medium" },
      ]);
      setSelected((prev) => new Set(prev).add(id));
      setCustomText("");
    } catch (err) {
      setQuickAddError(err instanceof Error ? err.message : String(err));
    } finally {
      setQuickAddBusy(false);
    }
  }

  async function generate(append: boolean) {
    setState((prev) => (append && prev.status === "ready" ? prev : { status: "loading" }));
    const req: QuestionBankRequest = {
      role: role.trim() || "Software Engineer",
      seniority,
      jd_text: jdText.trim(),
      n_behavioral: parseInt(nBehavioral, 10) || 0,
      n_system_design: parseInt(nSystem, 10) || 0,
      n_technical: parseInt(nTechnical, 10) || 0,
    };
    try {
      const data = await apiPost<QuestionBankResult>("/api/question-bank", req);
      setState((prev) => {
        if (append && prev.status === "ready") {
          const existingTexts = new Set(prev.questions.map((q) => q.text.toLowerCase()));
          const fresh = data.questions.filter((q) => !existingTexts.has(q.text.toLowerCase()));
          return { status: "ready", questions: [...prev.questions, ...fresh] };
        }
        return { status: "ready", questions: data.questions };
      });
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  const questions = state.status === "ready" ? state.questions : [];

  function toggleSelect(id: number | null | undefined) {
    if (id == null) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const usedCategories = useMemo(
    () => [...new Set(questions.map((q) => q.category))],
    [questions],
  );
  const practiceHref = `/interview/?role=${encodeURIComponent(role)}&seniority=${seniority}${
    usedCategories.length ? `&focus=${usedCategories.join(",")}` : ""
  }`;
  const selectedIds = [...selected];
  const drillHref = `/interview/?mode=drill&bank_ids=${selectedIds.join(",")}&role=${encodeURIComponent(role)}&seniority=${seniority}`;
  const fullHref = `/full-interview/?bank_ids=${selectedIds.join(",")}&role=${encodeURIComponent(role)}&seniority=${seniority}`;

  return (
    <>
      <section className="card">
        <h2>Question bank</h2>
        <p className="subtitle">
          Generate a tailored study list for a role. Paste a job description for sharper,
          competency-mapped questions.
        </p>

        <div className="form-grid">
          <div>
            <label className="field-label" htmlFor="qbRole">
              Role
            </label>
            <input
              id="qbRole"
              type="text"
              value={role}
              placeholder="e.g. Backend Engineer"
              onChange={(e) => setRole(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="qbSeniority">
              Seniority
            </label>
            <select
              id="qbSeniority"
              value={seniority}
              onChange={(e) => setSeniority(e.target.value as Seniority)}
            >
              <option value="junior">Junior</option>
              <option value="mid">Mid</option>
              <option value="senior">Senior</option>
              <option value="staff">Staff</option>
            </select>
          </div>
          <div className="full">
            <label className="field-label" htmlFor="qbJd">
              Job description (optional)
            </label>
            <textarea
              id="qbJd"
              value={jdText}
              placeholder="Paste the job description here..."
              onChange={(e) => setJdText(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="qbBehavioral">
              Behavioral
            </label>
            <input
              id="qbBehavioral"
              type="number"
              min={0}
              max={8}
              value={nBehavioral}
              onChange={(e) => setNBehavioral(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="qbSystem">
              System design
            </label>
            <input
              id="qbSystem"
              type="number"
              min={0}
              max={8}
              value={nSystem}
              onChange={(e) => setNSystem(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="qbTechnical">
              Technical concepts
            </label>
            <input
              id="qbTechnical"
              type="number"
              min={0}
              max={8}
              value={nTechnical}
              onChange={(e) => setNTechnical(e.target.value)}
            />
          </div>
        </div>

        <div className="actions-row">
          <button
            className="btn primary"
            onClick={() => generate(false)}
            disabled={state.status === "loading"}
          >
            {state.status === "loading" ? "Generating…" : "Generate questions"}
          </button>
        </div>
        {state.status === "loading" && (
          <p className="hint-text">Local model — generation can take up to a minute.</p>
        )}
      </section>

      <section className="card">
        <h2>Quick add</h2>
        <p className="subtitle">
          The classic HR screening questions (&ldquo;tell me about yourself&rdquo;, salary
          expectations, why us) with your target company filled in — plus any question of your own.
          Everything lands in the bank, ready to drill.
        </p>
        <div className="form-grid">
          <div>
            <label className="field-label" htmlFor="qbCompany">
              Target company (optional)
            </label>
            <input
              id="qbCompany"
              type="text"
              value={company}
              placeholder="e.g. Google"
              onChange={(e) => setCompany(e.target.value)}
            />
          </div>
          <div className="quick-add-action">
            <button className="btn" onClick={addHrSet} disabled={quickAddBusy}>
              {quickAddBusy ? "Adding…" : "Add HR question set"}
            </button>
          </div>
          <div className="full">
            <label className="field-label" htmlFor="qbCustom">
              Your own question
            </label>
            <div className="custom-question-row">
              <input
                id="qbCustom"
                type="text"
                value={customText}
                placeholder="e.g. Walk me through your most recent project."
                onChange={(e) => setCustomText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addCustomQuestion();
                }}
              />
              <button
                className="btn"
                onClick={addCustomQuestion}
                disabled={quickAddBusy || !customText.trim()}
              >
                Add
              </button>
            </div>
          </div>
        </div>
        {quickAddError && <p className="hint-text">Could not add: {quickAddError}</p>}
      </section>

      {state.status === "loading" && (
        <section className="card">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div className="skeleton skeleton-row" key={i} />
          ))}
        </section>
      )}

      {state.status === "error" && (
        <section className="card">
          <div className="error-card">
            <div className="icon">⚠️</div>
            <div>Could not generate questions: {state.message}</div>
            <button className="btn primary retry-btn" onClick={() => generate(false)}>
              Retry
            </button>
          </div>
        </section>
      )}

      {state.status === "ready" && (
        <section className="card">
          <div className="actions-row" style={{ marginTop: 0, marginBottom: 16 }}>
            <Link href={practiceHref} className="btn primary">
              Practice this set
            </Link>
            <button className="btn" onClick={() => generate(true)}>
              Generate more
            </button>
          </div>
          <p className="subtitle">
            Starts a live interview tuned to this role — the interviewer generates questions in the
            same categories. Check questions below to drill or run a full interview on just those.
          </p>
          <div className="qb-list">
            {questions.map((q, i) => (
              <div className={"qb-item" + (q.id != null && selected.has(q.id) ? " selected" : "")} key={q.id ?? i}>
                <label className="qb-select">
                  <input
                    type="checkbox"
                    checked={q.id != null && selected.has(q.id)}
                    disabled={q.id == null}
                    onChange={() => toggleSelect(q.id)}
                  />
                </label>
                <div className="qb-body">
                  <div className="question-meta">
                    <span className={"badge cat-" + q.category}>{humanize(q.category)}</span>
                    <span className={"badge diff-" + q.difficulty}>{q.difficulty}</span>
                  </div>
                  <div>{q.text}</div>
                  {q.targets_competency && (
                    <div className="qb-competency">Competency: {q.targets_competency}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {selected.size > 0 && (
        <div className="qb-selection-bar material">
          <span>{selected.size} selected</span>
          <div className="actions-row" style={{ marginTop: 0 }}>
            <Link href={drillHref} className="btn primary">
              Drill {selected.size} selected
            </Link>
            <Link href={fullHref} className="btn">
              Full Interview with these
            </Link>
            <button className="btn ghost" onClick={() => setSelected(new Set())}>
              Clear
            </button>
          </div>
        </div>
      )}
    </>
  );
}
