"use client";

import { useEffect, useMemo, useRef } from "react";
import type { SessionSummary, TrendPoint } from "@/lib/types";
import { humanize } from "@/lib/format";
import { getChartColors } from "@/lib/chartTheme";
import { useTheme } from "@/lib/theme";

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { version } = useTheme();

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 100;
    const h = canvas.clientHeight || 28;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (values.length < 2) return;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const step = w / (values.length - 1);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = i * step;
      const y = h - 3 - ((v - min) / range) * (h - 6);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    // last-point dot
    const lastX = (values.length - 1) * step;
    const lastY = h - 3 - ((values[values.length - 1] - min) / range) * (h - 6);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(lastX, lastY, 2, 0, Math.PI * 2);
    ctx.fill();
  }, [values, color, version]);

  return <canvas ref={ref} className="spark" />;
}

/** KPI row above the dashboard's charts: total sessions, recent trend, best/
 * worst category, and average confidence with a sparkline. */
export default function StatTiles({
  sessions,
  trends,
}: {
  sessions: SessionSummary[];
  trends: TrendPoint[];
}) {
  const colors = useMemo(() => getChartColors(), [trends]);

  const completed = trends.length;
  const last5 = trends.slice(-5);
  const prev5 = trends.slice(-10, -5);
  const avg = (pts: TrendPoint[]) => {
    const scored = pts.map((p) => p.overall_score).filter((v): v is number => v != null);
    return scored.length ? scored.reduce((a, b) => a + b, 0) / scored.length : null;
  };
  const avgLast5 = avg(last5);
  const avgPrev5 = avg(prev5);
  const delta = avgLast5 != null && avgPrev5 != null ? avgLast5 - avgPrev5 : null;

  const categoryAverages = useMemo(() => {
    const buckets: Record<string, number[]> = {};
    for (const t of trends) {
      for (const [cat, v] of Object.entries(t.category_scores || {})) {
        (buckets[cat] ??= []).push(v);
      }
    }
    return Object.entries(buckets)
      .map(([cat, vals]) => [cat, vals.reduce((a, b) => a + b, 0) / vals.length] as const)
      .sort((a, b) => b[1] - a[1]);
  }, [trends]);
  const strongest = categoryAverages[0];
  const weakest = categoryAverages[categoryAverages.length - 1];

  const confidenceValues = trends
    .map((t) => t.avg_confidence)
    .filter((v): v is number => v != null);
  const avgConfidence = confidenceValues.length
    ? confidenceValues.reduce((a, b) => a + b, 0) / confidenceValues.length
    : null;

  return (
    <div className="stat-tiles">
      <div className="stat-tile">
        <div className="lbl">Sessions</div>
        <div className="val-row">
          <span className="val">{sessions.length}</span>
        </div>
        <div className="sub">{completed} completed</div>
      </div>

      <div className="stat-tile">
        <div className="lbl">Avg overall (last 5)</div>
        <div className="val-row">
          <span className="val">{avgLast5 != null ? avgLast5.toFixed(1) : "—"}</span>
          {delta != null && (
            <span className={"delta " + (delta >= 0 ? "up" : "down")}>
              {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}
            </span>
          )}
        </div>
        <div className="sub">vs previous 5 sessions</div>
      </div>

      <div className="stat-tile">
        <div className="lbl">Strongest / weakest</div>
        {strongest && weakest ? (
          <>
            <div className="val-row">
              <span className="val" style={{ fontSize: "1rem" }}>
                {humanize(strongest[0])}
              </span>
            </div>
            <div className="sub">
              weakest: {humanize(weakest[0])} ({weakest[1].toFixed(1)})
            </div>
          </>
        ) : (
          <div className="val-row">
            <span className="val" style={{ fontSize: "1rem" }}>—</span>
          </div>
        )}
      </div>

      <div className="stat-tile">
        <div className="lbl">Avg confidence</div>
        <div className="val-row">
          <span className="val">{avgConfidence != null ? Math.round(avgConfidence) : "—"}</span>
          <span className="sub" style={{ marginTop: 0 }}>/100</span>
        </div>
        {confidenceValues.length >= 2 && (
          <Sparkline values={confidenceValues} color={colors.series[0]} />
        )}
      </div>
    </div>
  );
}
