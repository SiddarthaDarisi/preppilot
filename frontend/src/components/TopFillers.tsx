import type { StatsResult } from "@/lib/types";

/** "Filler habits" card: the user's most frequent filler words across all
 * sessions, as horizontal bars (reuses the score-bar styling). */
export default function TopFillers({ stats }: { stats: StatsResult }) {
  const top = stats.top_fillers;
  if (!top || top.length === 0) return null;
  const max = top[0].count || 1;

  return (
    <section className="card">
      <h2>Filler habits</h2>
      <p className="subtitle">Your most frequent filler words across all sessions.</p>
      <div className="score-bars">
        {top.map((f) => (
          <div className="score-bar-row" key={f.word}>
            <span className="lbl">{f.word}</span>
            <div className="score-bar-track">
              <div
                className="score-bar-fill s-amber"
                style={{ width: `${Math.max(4, (f.count / max) * 100)}%` }}
              />
            </div>
            <span className="num">{f.count}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
