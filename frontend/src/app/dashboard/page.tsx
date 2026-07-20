"use client";

/**
 * PrepPilot — dashboard page.
 *
 * Loads /api/sessions into a history table (row click opens a detail drawer
 * fed by /api/sessions/{id}) and /api/trends into two hand-rolled canvas
 * line charts (no external libraries; fully offline). Chart colors come
 * from lib/chartTheme.ts (CSS custom properties) instead of a hardcoded
 * palette, so both charts follow the dark/light toggle.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiDelete } from "@/lib/api";
import type { SessionDetail, SessionSummary, StatsResult, TrendPoint } from "@/lib/types";
import { fmtShortDate, humanize } from "@/lib/format";
import { getChartColors } from "@/lib/chartTheme";
import { useTheme } from "@/lib/theme";
import TrendsChart, { type ChartSeries } from "@/components/TrendsChart";
import StatTiles from "@/components/StatTiles";
import TopFillers from "@/components/TopFillers";
import CompetencyHeatmap from "@/components/CompetencyHeatmap";
import SessionTable, { SessionTableSkeleton } from "@/components/SessionTable";
import SessionDetailDrawer from "@/components/SessionDetailDrawer";
import { ToastHost, useToasts } from "@/components/Toasts";

type LoadState<T> =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; data: T };

function ChartSkeleton() {
  return <div className="skeleton" style={{ height: 360, borderRadius: "var(--radius)" }} />;
}

export default function DashboardPage() {
  const { toasts, toast, dismiss } = useToasts();
  const { version } = useTheme();

  const [sessionsState, setSessionsState] = useState<LoadState<SessionSummary[]>>({
    status: "loading",
  });
  const [trendsState, setTrendsState] = useState<LoadState<TrendPoint[]>>({
    status: "loading",
  });
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  // ---------------------------------------------------------------- data

  useEffect(() => {
    let cancelled = false;
    setSessionsState({ status: "loading" });
    setTrendsState({ status: "loading" });
    apiGet<SessionSummary[]>("/api/sessions")
      .then((s) => {
        if (!cancelled) setSessionsState({ status: "ready", data: s });
      })
      .catch(() => {
        if (!cancelled) setSessionsState({ status: "error" });
      });
    apiGet<TrendPoint[]>("/api/trends")
      .then((t) => {
        if (!cancelled) setTrendsState({ status: "ready", data: t });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setTrendsState({ status: "error" });
          toast(
            "Could not load trends: " +
              (err instanceof Error ? err.message : String(err)),
          );
        }
      });
    apiGet<StatsResult>("/api/stats")
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch(() => {
        /* filler-habits card is optional — hide it silently on failure */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey, toast]);

  const openDetail = useCallback((sessionId: number) => {
    setDrawerOpen(true);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    apiGet<SessionDetail>("/api/sessions/" + sessionId)
      .then((d) => setDetail(d))
      .catch(() => setDetailError("Could not load session detail."))
      .finally(() => setDetailLoading(false));
  }, []);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  const deleteSession = useCallback(
    (id: number) => {
      if (!window.confirm("Delete this session and its feedback? This can't be undone.")) return;
      apiDelete("/api/sessions/" + id)
        .then(() => setReloadKey((k) => k + 1))
        .catch(() => toast("Could not delete the session."));
    },
    [toast],
  );

  const clearAll = useCallback(() => {
    if (!window.confirm("Delete ALL sessions and history? This can't be undone.")) return;
    apiDelete("/api/sessions")
      .then(() => setReloadKey((k) => k + 1))
      .catch(() => toast("Could not clear sessions."));
  }, [toast]);

  // ---------------------------------------------------------------- charts

  const trends = trendsState.status === "ready" ? trendsState.data : [];
  const sessions = sessionsState.status === "ready" ? sessionsState.data : [];

  const xLabels = useMemo(
    () => trends.map((t) => fmtShortDate(t.created_at)),
    [trends],
  );

  const colors = useMemo(() => getChartColors(), [version]);

  // Chart 1: overall + per-category scores (0-10 scale).
  const scoreSeries = useMemo<ChartSeries[]>(() => {
    if (!trends.length) return [];
    const categories = [
      ...new Set(trends.flatMap((t) => Object.keys(t.category_scores || {}))),
    ];
    return [
      {
        label: "overall",
        color: colors.series[0],
        values: trends.map((t) => t.overall_score ?? null),
        fill: true,
      },
      ...categories.map((cat, i) => ({
        label: humanize(cat),
        color: colors.series[(i + 1) % colors.series.length],
        values: trends.map((t) => (t.category_scores || {})[cat] ?? null),
      })),
    ];
  }, [trends, colors]);

  // Chart 2: delivery metrics, normalized to a shared 0-100 axis.
  const deliverySeries = useMemo<ChartSeries[]>(() => {
    if (!trends.length) return [];
    return [
      {
        label: "avg WPM ÷ 2",
        color: colors.series[4],
        values: trends.map((t) => (t.avg_wpm == null ? null : t.avg_wpm / 2)),
      },
      {
        label: "filler rate %",
        color: colors.series[5],
        values: trends.map((t) =>
          t.avg_filler_rate == null ? null : t.avg_filler_rate * 100,
        ),
      },
      {
        label: "confidence (0-100)",
        color: colors.series[1],
        values: trends.map((t) => t.avg_confidence ?? null),
        fill: true,
      },
      {
        label: "expressiveness (0-100)",
        color: colors.series[3],
        values: trends.map((t) => t.avg_expressiveness ?? null),
      },
    ];
  }, [trends, colors]);

  const bothErrored = sessionsState.status === "error" && trendsState.status === "error";

  // ---------------------------------------------------------------- render

  if (bothErrored) {
    return (
      <section className="card">
        <div className="error-card">
          <div className="icon">⚠️</div>
          <div>Could not reach the backend — is it running?</div>
          <button className="btn primary retry-btn" onClick={retry}>
            Retry
          </button>
        </div>
      </section>
    );
  }

  return (
    <>
      {sessionsState.status === "ready" && trendsState.status === "ready" && (
        <StatTiles sessions={sessions} trends={trends} />
      )}

      <div className="charts-grid">
        <section className="card chart-card">
          <h2>Scores over time</h2>
          <p className="subtitle">
            Overall and per-category scores for each session.
          </p>
          {trendsState.status === "loading" ? (
            <ChartSkeleton />
          ) : (
            <TrendsChart xLabels={xLabels} series={scoreSeries} yMin={0} yMax={10} />
          )}
        </section>
        <section className="card chart-card">
          <h2>Delivery over time</h2>
          <p className="subtitle">
            Speaking pace, filler rate, confidence and expressiveness per session.
          </p>
          {trendsState.status === "loading" ? (
            <ChartSkeleton />
          ) : (
            <TrendsChart xLabels={xLabels} series={deliverySeries} yMin={0} yMax={100} />
          )}
        </section>
      </div>

      {stats && <CompetencyHeatmap competencies={stats.competencies} />}
      {stats && <TopFillers stats={stats} />}

      <section className="card">
        <div className="section-head">
          <div>
            <h2>Session history</h2>
            <p className="subtitle">
              Click a session to review its questions, feedback and report.
            </p>
          </div>
          {sessions.length > 0 && (
            <button className="btn ghost danger sm" onClick={clearAll}>
              Clear all
            </button>
          )}
        </div>
        {sessionsState.status === "loading" ? (
          <SessionTableSkeleton />
        ) : sessionsState.status === "error" ? (
          <div className="error-card">
            <div>Could not load sessions.</div>
            <button className="btn retry-btn" onClick={retry}>
              Retry
            </button>
          </div>
        ) : (
          <SessionTable sessions={sessions} onSelect={openDetail} onDelete={deleteSession} />
        )}
      </section>

      <SessionDetailDrawer
        open={drawerOpen}
        loading={detailLoading}
        detail={detail}
        error={detailError}
        onClose={closeDrawer}
      />

      <ToastHost toasts={toasts} onDismiss={dismiss} />
    </>
  );
}
