import type { DeliveryMetrics } from "@/lib/types";
import { computeMistakeAlerts } from "@/lib/alerts";

/** Instant amber/red chips flagging delivery issues, before LLM feedback. */
export default function MistakeAlerts({ metrics }: { metrics: DeliveryMetrics | null }) {
  if (!metrics) return null;
  const alerts = computeMistakeAlerts(metrics);
  if (alerts.length === 0) return null;
  return (
    <div className="alert-chips" role="status" aria-label="Delivery alerts">
      {alerts.map((a) => (
        <span className={"alert-chip" + (a.severity === "bad" ? " bad" : "")} key={a.id}>
          {a.text}
        </span>
      ))}
    </div>
  );
}
