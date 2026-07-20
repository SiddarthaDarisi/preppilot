"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getChartColors } from "@/lib/chartTheme";
import { useTheme } from "@/lib/theme";

export interface ChartSeries {
  label: string;
  color: string;
  values: (number | null)[];
  /** Draw a translucent area fill under this series (use for the primary
   * series only — stacking fills for every series reads as noise). */
  fill?: boolean;
}

interface HoverPoint {
  x: number;
  y: number;
  label: string;
  value: number;
  xLabel: string;
}

interface Tooltip {
  x: number;
  y: number;
  label: string;
  value: number;
  xLabel: string;
}

/**
 * Hand-rolled multi-series line chart on a canvas (no chart libraries).
 * Theme-aware (redraws on theme toggle via chartTheme.ts), with a gradient
 * fill under the primary series, a real HTML tooltip (the old version used
 * the `title` attribute), and a clickable legend that toggles series
 * visibility.
 */
export default function TrendsChart({
  xLabels,
  series,
  yMin,
  yMax,
  yTicks = 5,
  height = 360,
  emptyText = "No sessions yet — run an interview first.",
}: {
  xLabels: string[];
  series: ChartSeries[];
  yMin: number;
  yMax: number;
  yTicks?: number;
  height?: number;
  emptyText?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hoverPointsRef = useRef<HoverPoint[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);
  const { version } = useTheme();

  const toggleSeries = useCallback((label: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const colors = getChartColors();
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 640;
    const cssH = height;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    canvas.style.height = cssH + "px";
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, cssW, cssH);

    const pad = { top: 16, right: 44, bottom: 34, left: 40 };
    const plotW = cssW - pad.left - pad.right;
    const plotH = cssH - pad.top - pad.bottom;
    const n = xLabels.length;

    const xPos = (i: number) =>
      pad.left + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
    const yPos = (v: number) =>
      pad.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

    const fontFamily = getComputedStyle(document.body).fontFamily;
    const visibleSeries = series.filter((s) => !hidden.has(s.label));

    // Grid + y-axis labels.
    ctx.font = "11px " + fontFamily;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let t = 0; t <= yTicks; t++) {
      const v = yMin + ((yMax - yMin) * t) / yTicks;
      const y = yPos(v);
      ctx.strokeStyle = colors.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(cssW - pad.right, y);
      ctx.stroke();
      ctx.fillStyle = colors.axisText;
      ctx.fillText(String(Math.round(v * 10) / 10), pad.left - 8, y);
    }

    // X-axis labels (thin out when crowded).
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const step = Math.max(1, Math.ceil(n / 8));
    for (let i = 0; i < n; i++) {
      if (i % step !== 0 && i !== n - 1) continue;
      ctx.fillStyle = colors.axisText;
      ctx.fillText(xLabels[i], xPos(i), pad.top + plotH + 8);
    }

    // Axis lines.
    ctx.strokeStyle = colors.grid;
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top);
    ctx.lineTo(pad.left, pad.top + plotH);
    ctx.lineTo(cssW - pad.right, pad.top + plotH);
    ctx.stroke();

    // Series lines + optional area fill + points. Null values create gaps.
    const hoverPoints: HoverPoint[] = [];
    for (const s of visibleSeries) {
      const points: { x: number; y: number }[] = [];
      s.values.forEach((v, i) => {
        if (v === null || v === undefined || Number.isNaN(v)) return;
        const x = xPos(i);
        const y = yPos(Math.max(yMin, Math.min(yMax, v)));
        points.push({ x, y });
        hoverPoints.push({ x, y, label: s.label, value: v, xLabel: xLabels[i] });
      });

      if (s.fill && points.length > 1) {
        const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
        grad.addColorStop(0, s.color + "33");
        grad.addColorStop(1, s.color + "00");
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.moveTo(points[0].x, pad.top + plotH);
        points.forEach((p) => ctx.lineTo(p.x, p.y));
        ctx.lineTo(points[points.length - 1].x, pad.top + plotH);
        ctx.closePath();
        ctx.fill();
      }

      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      points.forEach((p, i) => {
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.stroke();

      ctx.fillStyle = s.color;
      points.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
        ctx.fill();
      });

      // Last-point value label.
      if (points.length > 0) {
        const last = points[points.length - 1];
        const lastVal = s.values.filter((v) => v != null).slice(-1)[0] as number;
        ctx.font = "10px " + fontFamily;
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillStyle = s.color;
        ctx.fillText(String(Math.round(lastVal * 10) / 10), last.x + 6, last.y);
      }
    }
    hoverPointsRef.current = hoverPoints;

    // Empty state.
    if (n === 0) {
      ctx.fillStyle = colors.axisText;
      ctx.font = "13px " + fontFamily;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(emptyText, cssW / 2, cssH / 2);
    }
  }, [xLabels, series, yMin, yMax, yTicks, height, emptyText, hidden]);

  // Draw on mount / data change / theme change; redraw on resize.
  useEffect(() => {
    draw();
  }, [draw, version]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [draw]);

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let best: HoverPoint | null = null;
    let bestDist = 14 * 14; // 14px radius
    for (const p of hoverPointsRef.current) {
      const d = (p.x - mx) ** 2 + (p.y - my) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = p;
      }
    }
    if (best) {
      setTooltip({ x: best.x, y: best.y, label: best.label, value: best.value, xLabel: best.xLabel });
      canvas.style.cursor = "pointer";
    } else {
      setTooltip(null);
      canvas.style.cursor = "default";
    }
  }

  return (
    <>
      <canvas
        ref={canvasRef}
        width={640}
        height={height}
        onMouseMove={onMouseMove}
        onMouseLeave={() => setTooltip(null)}
      />
      {tooltip && (
        <div
          className="chart-tooltip visible"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.xLabel} — {tooltip.label}: {Math.round(tooltip.value * 100) / 100}
        </div>
      )}
      {series.length > 0 && (
        <div className="chart-legend">
          {series.map((s) => (
            <button
              type="button"
              className={"key" + (hidden.has(s.label) ? " muted" : "")}
              key={s.label}
              onClick={() => toggleSeries(s.label)}
              title={hidden.has(s.label) ? "Show series" : "Hide series"}
            >
              <span className="swatch" style={{ background: s.color }}></span>
              <span>{s.label}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
