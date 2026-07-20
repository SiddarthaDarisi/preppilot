"use client";

import { useState } from "react";
import Link from "next/link";
import type { ReportResult } from "@/lib/types";
import ScoreGauge from "@/components/ScoreGauge";
import CategoryBars from "@/components/CategoryBars";
import { MetricTiles } from "@/components/MetricsRow";

// Mirrors backend config.yaml `analytics.wpm_range` / `filler_target_rate` —
// not exposed over the API, so duplicated here for the target annotations.
const WPM_RANGE: [number, number] = [110, 160];
const FILLER_TARGET_RATE = 0.03;

function verdictFor(score: number): string {
  if (score >= 8) return "Strong session — you're close to interview-ready.";
  if (score >= 6) return "Solid foundation with a few clear things to tighten up.";
  if (score >= 4) return "Good start — the practice plan below targets your biggest gaps.";
  return "Early days — focus on the practice plan before your next attempt.";
}

/** End-of-session report panel. */
export default function ReportView({
  report,
  onNewSession,
  avgExpressiveness = null,
}: {
  report: ReportResult;
  onNewSession: () => void;
  avgExpressiveness?: number | null;
}) {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const overall = report.overall_score ?? 0;
  const d = report.delivery_summary || {
    avg_wpm: 0,
    avg_filler_rate: 0,
    avg_confidence: 0,
    biggest_habit_to_fix: "",
  };

  const categoryItems = Object.entries(report.category_scores || {}).map(
    ([category, value]) => ({ category, value }),
  );

  const lists: [string, string[] | undefined][] = [
    ["Strengths", report.strengths],
    ["Development areas", report.development_areas],
  ];

  const toggleChecked = (i: number) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  const wpmInRange = d.avg_wpm >= WPM_RANGE[0] && d.avg_wpm <= WPM_RANGE[1];
  const fillerOk = d.avg_filler_rate <= FILLER_TARGET_RATE;

  return (
    <section className="card">
      <h2>Session report</h2>
      <p className="subtitle">Here is how you did across the whole session.</p>

      <div className="report-hero">
        <ScoreGauge value={overall} />
        <div className="report-verdict">
          <p className="headline">{verdictFor(overall)}</p>
          <p className="sub">
            Overall score {overall.toFixed(1)} / 10 across {categoryItems.length || "all"}{" "}
            categor{categoryItems.length === 1 ? "y" : "ies"}.
          </p>
        </div>
      </div>

      {categoryItems.length > 0 && (
        <>
          <div className="fb-section-title">Category breakdown</div>
          <CategoryBars items={categoryItems} />
        </>
      )}

      <div className="two-col">
        {lists.map(([title, items]) =>
          Array.isArray(items) && items.length ? (
            <div key={title}>
              <div className="fb-section-title">{title}</div>
              <ul className="plain-list">
                {items.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
      </div>

      <div className="fb-section-title">Delivery summary</div>
      <MetricTiles
        tiles={[
          [
            String(Math.round(d.avg_wpm || 0)),
            "Avg WPM",
            wpmInRange ? "within target 110–160" : "target 110–160",
          ],
          [
            ((d.avg_filler_rate || 0) * 100).toFixed(1) + "%",
            "Filler rate",
            fillerOk ? "at/under target 3%" : "target < 3%",
          ],
          [String(Math.round(d.avg_confidence || 0)), "Confidence", undefined],
          ...(avgExpressiveness != null
            ? ([[String(Math.round(avgExpressiveness)), "Expressiveness", "tone variety, 0-100"]] as [
                string,
                string,
                string,
              ][])
            : []),
        ]}
      />
      {d.biggest_habit_to_fix && (
        <p className="coaching-text">
          Biggest habit to fix: {d.biggest_habit_to_fix}
        </p>
      )}

      {Array.isArray(report.practice_plan) && report.practice_plan.length > 0 && (
        <>
          <div className="fb-section-title">Practice plan</div>
          <div className="practice-plan-list">
            {report.practice_plan.map((item, i) => (
              <label className={"practice-item" + (checked.has(i) ? " checked" : "")} key={i}>
                <input
                  type="checkbox"
                  checked={checked.has(i)}
                  onChange={() => toggleChecked(i)}
                />
                <div>
                  <div className="focus">{item.focus || ""}</div>
                  <div className="drill">{item.drill || ""}</div>
                  {item.target_metric && (
                    <div className="target">Target: {item.target_metric}</div>
                  )}
                </div>
              </label>
            ))}
          </div>
        </>
      )}

      <div className="actions-row">
        <Link href="/dashboard/" className="btn primary">
          View dashboard
        </Link>
        <button className="btn ghost" onClick={onNewSession}>
          Start a new session
        </button>
        <span className="spacer"></span>
        <button className="btn ghost print-hide" onClick={() => window.print()}>
          Print / save PDF
        </button>
      </div>
    </section>
  );
}
