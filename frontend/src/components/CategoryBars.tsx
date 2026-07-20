import { humanize, scoreColor } from "@/lib/format";

export interface CategoryBarItem {
  category: string;
  value: number;
}

/** Horizontal 0-max bar per category score, for the end-of-session report. */
export default function CategoryBars({
  items,
  max = 10,
}: {
  items: CategoryBarItem[];
  max?: number;
}) {
  return (
    <div className="score-bars">
      {items.map((it) => {
        const pct = Math.max(0, Math.min(100, (it.value / max) * 100));
        return (
          <div className="score-bar-row" key={it.category}>
            <span className="lbl">{humanize(it.category)}</span>
            <div className="score-bar-track">
              <div
                className="score-bar-fill"
                style={{ width: `${pct}%`, background: scoreColor(it.value) }}
              />
            </div>
            <span className="num">{it.value.toFixed(1)}</span>
          </div>
        );
      })}
    </div>
  );
}
