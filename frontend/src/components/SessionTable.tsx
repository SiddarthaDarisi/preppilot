import type { SessionSummary } from "@/lib/types";
import { fmtDate, fmtRelativeDate } from "@/lib/format";
import ScoreChip from "@/components/ScoreChip";

export function SessionTableSkeleton() {
  return (
    <div>
      {[0, 1, 2, 3].map((i) => (
        <div className="skeleton skeleton-row" key={i} />
      ))}
    </div>
  );
}

function EmptyIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M8 4v-1M16 4v-1" strokeLinecap="round" />
    </svg>
  );
}

/** Session history table; rows open the detail drawer. */
export default function SessionTable({
  sessions,
  onSelect,
  onDelete,
}: {
  sessions: SessionSummary[];
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  if (!sessions.length) {
    return (
      <div className="empty-state">
        <EmptyIcon />
        <div>No sessions yet. Run your first mock interview!</div>
      </div>
    );
  }

  const sorted = [...sessions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  return (
    <table className="plain-table clickable">
      <thead>
        <tr>
          <th>Date</th>
          <th>Role</th>
          <th>Seniority</th>
          <th>Status</th>
          <th>Questions</th>
          <th>Overall</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((s) => (
          <tr
            key={s.id}
            tabIndex={0}
            onClick={() => onSelect(s.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(s.id);
              }
            }}
          >
            <td className="rel-date" title={fmtDate(s.created_at)}>
              {fmtRelativeDate(s.created_at)}
            </td>
            <td>{s.role}</td>
            <td>{s.seniority}</td>
            <td>{s.status}</td>
            <td>{String(s.question_count)}</td>
            <td>
              {s.overall_score != null ? (
                <ScoreChip value={s.overall_score} digits={1} />
              ) : (
                "—"
              )}
            </td>
            <td>
              <button
                className="row-delete"
                title="Delete this session"
                aria-label={`Delete session for ${s.role}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.id);
                }}
              >
                ✕
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
