import { scoreClass } from "@/lib/format";

export interface ScoreBarItem {
  label: string;
  value: number;
}

/** A labeled 0-max bar per score — used for the per-answer rubric breakdown
 * in both FeedbackCard (live interview) and SessionDetailDrawer (history),
 * so the two views read consistently. */
export default function ScoreBars({
  items,
  max = 10,
}: {
  items: ScoreBarItem[];
  max?: number;
}) {
  return (
    <div className="score-bars">
      {items.map((it) => (
        <div className="score-bar-row" key={it.label}>
          <span className="lbl">{it.label}</span>
          <div className="score-bar-track">
            <div
              className={"score-bar-fill " + scoreClass(it.value)}
              style={{ width: `${Math.max(0, Math.min(100, (it.value / max) * 100))}%` }}
            />
          </div>
          <span className="num">
            {Number.isInteger(it.value) ? it.value : it.value.toFixed(1)}
          </span>
        </div>
      ))}
    </div>
  );
}
