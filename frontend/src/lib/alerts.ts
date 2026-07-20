/**
 * Instant, rule-based delivery alerts computed from a DeliveryMetrics message
 * — shown seconds after the answer ends, before the LLM feedback arrives.
 * Pure thresholds (no model call), so there's zero latency. Thresholds mirror
 * the delivery targets used by backend/analytics/metrics.py.
 */

import type { DeliveryMetrics } from "@/lib/types";

export interface MistakeAlert {
  id: string;
  severity: "warn" | "bad";
  text: string;
}

export function computeMistakeAlerts(m: DeliveryMetrics): MistakeAlert[] {
  const alerts: MistakeAlert[] = [];
  const hasAudio = m.duration_sec > 0;

  if (m.filler_rate > 0.03) {
    alerts.push({
      id: "fillers",
      severity: m.filler_rate > 0.08 ? "bad" : "warn",
      text: `Fillers ${m.filler_count}× (${(m.filler_rate * 100).toFixed(1)}%) — aim under 3%`,
    });
  }

  if (hasAudio && m.wpm > 0 && m.wpm < 110) {
    alerts.push({
      id: "pace-slow",
      severity: "warn",
      text: `Pace ${Math.round(m.wpm)} WPM — a bit slow (target 110–160)`,
    });
  }
  if (hasAudio && m.wpm > 160) {
    alerts.push({
      id: "pace-fast",
      severity: "warn",
      text: `Pace ${Math.round(m.wpm)} WPM — a bit fast (target 110–160)`,
    });
  }

  if (hasAudio && m.pause_ratio > 0.25) {
    alerts.push({
      id: "pauses",
      severity: "warn",
      text: `Silent ${Math.round(m.pause_ratio * 100)}% of your answer — tighten the gaps`,
    });
  }

  if (m.long_pause_count >= 2) {
    alerts.push({
      id: "long-pauses",
      severity: "warn",
      text: `${m.long_pause_count} long pauses (>1.5s) — pause less, or think out loud`,
    });
  }

  if ((hasAudio && m.duration_sec < 8) || m.word_count < 20) {
    alerts.push({
      id: "too-short",
      severity: "bad",
      text: "Very short answer — add Situation, Task, Action, Result detail",
    });
  }

  if (m.pitch_mean_hz > 0 && m.pitch_std_hz < 15) {
    alerts.push({
      id: "monotone",
      severity: "warn",
      text: "Monotone delivery — vary your pitch to keep the interviewer engaged",
    });
  }

  return alerts;
}
