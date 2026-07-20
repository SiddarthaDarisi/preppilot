"use client";

import { useEffect, useState } from "react";
import type { AnswerRecord, SessionDetail } from "@/lib/types";
import { fmtDate, humanize } from "@/lib/format";
import { apiPost } from "@/lib/api";
import ScoreChip from "@/components/ScoreChip";
import ScoreBars from "@/components/ScoreBars";
import DeliveryPanel from "@/components/DeliveryPanel";
import TranscriptText from "@/components/TranscriptText";
import { StarPills } from "@/components/FeedbackCard";

/** Persists this answer's question into the bank, then jumps to a 1-question drill. */
function DrillThisQuestionButton({
  question,
  category,
  competency,
  role,
  seniority,
}: {
  question: string;
  category: string;
  competency?: string;
  role: string;
  seniority: string;
}) {
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      const { id } = await apiPost<{ id: number }>("/api/question-bank/adopt", {
        text: question,
        category,
        role,
        seniority,
        targets_competency: competency || "",
      });
      window.location.href = `/interview/?mode=drill&bank_ids=${id}&role=${encodeURIComponent(role)}&seniority=${seniority}`;
    } catch {
      setBusy(false);
    }
  }
  return (
    <button className="btn ghost sm" onClick={go} disabled={busy}>
      {busy ? "Preparing…" : "Drill this question"}
    </button>
  );
}

function TranscriptBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > 220;
  return (
    <>
      <div className={"t" + (isLong && !expanded ? " clamped" : "")}>
        <TranscriptText text={text} />
      </div>
      {isLong && (
        <button className="show-more" onClick={() => setExpanded((e) => !e)}>
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </>
  );
}

function AnswerBlock({
  a,
  idx,
  role,
  seniority,
}: {
  a: AnswerRecord;
  idx: number;
  role: string;
  seniority: string;
}) {
  const scores = a.feedback?.scores;
  const scoreItems = scores
    ? (Object.entries(scores) as [string, number | null | undefined][])
        .filter(([, v]) => v != null)
        .map(([key, v]) => ({ label: humanize(key), value: v as number }))
    : [];

  return (
    <details className="answer-block" open={idx === 0}>
      <summary>
        <span className="badge qnum">Q{idx + 1}</span>
        <span className={"badge cat-" + a.category}>{humanize(a.category)}</span>
        {a.is_followup && <span className="badge followup">follow-up</span>}
        <span className="q">{a.question}</span>
        <span className="chev">▸</span>
      </summary>
      <div className="body">
        {a.transcript && <TranscriptBlock text={a.transcript} />}
        {a.feedback?.star_completeness && a.feedback?.star_applicable !== false && (
          <StarPills star={a.feedback.star_completeness} small />
        )}
        {scoreItems.length > 0 && <ScoreBars items={scoreItems} />}
        {a.feedback?.coaching_summary && (
          <div className="summary">{a.feedback.coaching_summary}</div>
        )}
        {a.metrics && (
          <>
            <div className="fb-section-title">Delivery</div>
            <DeliveryPanel metrics={a.metrics} compact />
          </>
        )}
        <div className="actions-row" style={{ marginTop: 10 }}>
          <DrillThisQuestionButton
            question={a.question}
            category={a.category}
            role={role}
            seniority={seniority}
          />
        </div>
      </div>
    </details>
  );
}

export function SessionDetailSkeleton() {
  return (
    <div>
      {[0, 1, 2].map((i) => (
        <div className="skeleton skeleton-row" key={i} style={{ height: 64 }} />
      ))}
    </div>
  );
}

/** Slide-in drawer with per-question scores + feedback and the report. */
export default function SessionDetailDrawer({
  open,
  loading,
  detail,
  error,
  onClose,
}: {
  open: boolean;
  loading: boolean;
  detail: SessionDetail | null;
  error: string | null;
  onClose: () => void;
}) {
  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const s = detail?.summary;
  const report = detail?.report;

  return (
    <>
      <div
        className={"drawer-overlay" + (open ? " open" : "")}
        onClick={onClose}
      ></div>
      <aside className={"detail-drawer" + (open ? " open" : "")}>
        <div className="drawer-header">
          <h3>
            {s
              ? `${s.role} (${s.seniority}) — ${fmtDate(s.created_at)}`
              : "Session detail"}
          </h3>
          <button className="btn ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          {loading && <SessionDetailSkeleton />}
          {!loading && error && <div className="empty-state">{error}</div>}

          {!loading &&
            !error &&
            detail &&
            (detail.answers || []).map((a, idx) => (
              <AnswerBlock
                a={a}
                idx={idx}
                role={s?.role || "Software Engineer"}
                seniority={s?.seniority || "mid"}
                key={a.question_id ?? idx}
              />
            ))}

          {!loading && !error && report && (
            <>
              <div className="fb-section-title">Session report</div>
              <div className="answer-block" style={{ padding: "14px 16px" }}>
                <div className="score-chips">
                  <ScoreChip
                    label="overall"
                    value={report.overall_score || 0}
                    digits={1}
                    overall
                  />
                  {Object.entries(report.category_scores || {}).map(
                    ([cat, v]) => (
                      <ScoreChip
                        key={cat}
                        label={humanize(cat)}
                        value={v}
                        digits={1}
                      />
                    ),
                  )}
                </div>

                {(
                  [
                    ["Strengths", report.strengths],
                    ["Development areas", report.development_areas],
                  ] as [string, string[] | undefined][]
                ).map(([title, items]) =>
                  Array.isArray(items) && items.length ? (
                    <div key={title}>
                      <div className="fb-section-title">{title}</div>
                      <ul className="plain-list">
                        {items.map((it, i) => (
                          <li key={i}>{it}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null,
                )}

                {Array.isArray(report.practice_plan) &&
                  report.practice_plan.length > 0 && (
                    <>
                      <div className="fb-section-title">Practice plan</div>
                      <ul className="plain-list">
                        {report.practice_plan.map((p, i) => (
                          <li key={i}>
                            {p.focus}: {p.drill}
                            {p.target_metric
                              ? ` (target: ${p.target_metric})`
                              : ""}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
