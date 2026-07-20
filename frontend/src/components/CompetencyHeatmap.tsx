import { humanize, scoreColor } from "@/lib/format";
import type { CompetencyAvg } from "@/lib/types";

/** "What to practice next" — avg overall score per competency across every
 * session, worst-first (already sorted server-side by get_competency_averages). */
export default function CompetencyHeatmap({ competencies }: { competencies: CompetencyAvg[] }) {
  if (!competencies || competencies.length === 0) return null;

  return (
    <section className="card">
      <h2>Competency heatmap</h2>
      <p className="subtitle">Average score per competency across every session — weakest first.</p>
      <div className="score-bars">
        {competencies.map((c) => (
          <div className="score-bar-row" key={c.name}>
            <span className="lbl">{humanize(c.name)}</span>
            <div className="score-bar-track">
              <div
                className="score-bar-fill"
                style={{ width: `${Math.max(4, (c.avg / 10) * 100)}%`, background: scoreColor(c.avg) }}
              />
            </div>
            <span className="num">{c.avg.toFixed(1)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
