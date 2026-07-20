import type { DeliveryMetrics } from "@/lib/types";

export function MetricTiles({
  tiles,
}: {
  tiles: [string, string, string?][];
}) {
  return (
    <div className="metrics-row">
      {tiles.map(([val, lbl, target]) => (
        <div className="metric-tile" key={lbl}>
          <span className="val">{val}</span>
          <span className="lbl">{lbl}</span>
          {target && <span className="target">{target}</span>}
        </div>
      ))}
    </div>
  );
}

/** Per-answer delivery metrics row + confidence gauge. */
export default function MetricsRow({ metrics }: { metrics: DeliveryMetrics }) {
  const conf = Math.max(0, Math.min(100, metrics.confidence_proxy || 0));
  const tiles: [string, string][] = [
    [String(Math.round(metrics.wpm)), "WPM"],
    [
      `${metrics.filler_count} (${(metrics.filler_rate * 100).toFixed(1)}%)`,
      "Fillers",
    ],
    [`${(metrics.pause_ratio * 100).toFixed(0)}%`, "Pause ratio"],
    [String(metrics.long_pause_count), "Long pauses"],
    [`${Math.round(metrics.pitch_std_hz)} Hz`, "Pitch variation"],
  ];
  return (
    <div>
      <MetricTiles tiles={tiles} />
      <div className="gauge-wrap">
        <span className="lbl fb-section-title">Confidence</span>
        <div className="gauge-track">
          <div className="gauge-fill" style={{ width: `${conf.toFixed(0)}%` }} />
        </div>
        <span className="gauge-num">{conf.toFixed(0)}/100</span>
      </div>
    </div>
  );
}
