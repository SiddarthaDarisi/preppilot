import type { DeliveryMetrics } from "@/lib/types";
import { MetricTiles } from "@/components/MetricsRow";

/**
 * Per-answer delivery/tone panel: confidence + expressiveness gauges, a pace
 * band, metric tiles, filler-word breakdown, and an optional (experimental)
 * SER tone chip. Used in the live coach column, the feedback card, and the
 * session-detail drawer. In text mode (duration_sec === 0) the audio-only
 * pieces (expressiveness gauge, pace band) are hidden.
 */
export default function DeliveryPanel({
  metrics,
  compact = false,
}: {
  metrics: DeliveryMetrics;
  compact?: boolean;
}) {
  const hasAudio = metrics.duration_sec > 0;
  const conf = Math.max(0, Math.min(100, metrics.confidence_proxy || 0));
  const expr = Math.max(0, Math.min(100, metrics.expressiveness || 0));

  // Pace marker: 60 WPM → 0%, 210 WPM → 100%, so 110→33.3%, 160→66.7%.
  const pacePct = Math.max(0, Math.min(100, ((metrics.wpm - 60) / 150) * 100));

  const fillerEntries = Object.entries(metrics.filler_words || {}).sort(
    (a, b) => b[1] - a[1],
  );

  return (
    <div className={"delivery-panel" + (compact ? " compact" : "")}>
      <div
        className="gauge-wrap"
        title="Transparent composite of fillers, pauses, pace and pitch variety"
      >
        <span className="lbl fb-section-title">Confidence</span>
        <div className="gauge-track">
          <div className="gauge-fill" style={{ width: `${conf.toFixed(0)}%` }} />
        </div>
        <span className="gauge-num">{conf.toFixed(0)}/100</span>
      </div>

      {hasAudio && (
        <div
          className="gauge-wrap"
          title="Tone variety: pitch variation + pitch range + loudness variation"
        >
          <span className="lbl fb-section-title">Expressiveness</span>
          <div className="gauge-track">
            <div className="gauge-fill" style={{ width: `${expr.toFixed(0)}%` }} />
          </div>
          <span className="gauge-num">{expr.toFixed(0)}/100</span>
        </div>
      )}

      {hasAudio && (
        <>
          <div className="pace-band">
            <div className="pace-zone slow" />
            <div className="pace-zone ok" />
            <div className="pace-zone fast" />
            <div className="pace-marker" style={{ left: `${pacePct}%` }} />
          </div>
          <div className="pace-caption">
            {Math.round(metrics.wpm)} WPM · target 110–160
          </div>
        </>
      )}

      <MetricTiles
        tiles={[
          [`${((metrics.pause_ratio || 0) * 100).toFixed(0)}%`, "Pause ratio", "< 25%"],
          [String(metrics.long_pause_count), "Long pauses", "> 1.5s each"],
          [
            `${metrics.filler_count} (${((metrics.filler_rate || 0) * 100).toFixed(1)}%)`,
            "Fillers",
            "target < 3%",
          ],
          [`${(metrics.duration_sec || 0).toFixed(0)}s`, "Duration"],
          [String(metrics.word_count), "Words"],
        ]}
      />

      {fillerEntries.length > 0 && (
        <div className="chip-row">
          {fillerEntries.map(([word, count]) => (
            <span className="filler-chip" key={word}>
              {word} ×{count}
            </span>
          ))}
        </div>
      )}

      {metrics.ser_label && (
        <span
          className="ser-chip"
          title="Optional speech-emotion model output — experimental, not a score input"
        >
          tone: {metrics.ser_label}
          {metrics.ser_confidence != null
            ? ` (${Math.round(metrics.ser_confidence * 100)}%)`
            : ""}{" "}
          · experimental
        </span>
      )}
    </div>
  );
}
