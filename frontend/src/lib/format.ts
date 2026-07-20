/** Shared formatting helpers. */

/** Map a 1-10 score to a color class: red < 5, amber 5-7, green > 7. */
export function scoreClass(v: number): string {
  if (v < 5) return "s-red";
  if (v <= 7) return "s-amber";
  return "s-green";
}

/** "Jul 19 10:32 AM" style date for tables and chart axes. */
export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
  );
}

/** "Jul 19" style short date for chart x labels. */
export function fmtShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Turn snake_case into words. */
export function humanize(s: string): string {
  return s.replace(/_/g, " ");
}

/** "2h ago" / "3d ago" / falls back to fmtShortDate beyond ~30 days. */
export function fmtRelativeDate(iso: string): string {
  const d = new Date(iso);
  const diffSec = (Date.now() - d.getTime()) / 1000;
  if (diffSec < 60) return "just now";
  const diffMin = diffSec / 60;
  if (diffMin < 60) return `${Math.floor(diffMin)}m ago`;
  const diffHr = diffMin / 60;
  if (diffHr < 24) return `${Math.floor(diffHr)}h ago`;
  const diffDay = diffHr / 24;
  if (diffDay < 30) return `${Math.floor(diffDay)}d ago`;
  return fmtShortDate(iso);
}

/** Map a 0-10 score to the same red/amber/green CSS variable name used by
 * scoreClass, but returns a `var(--x)` string for direct use in inline
 * styles (SVG fills etc.) rather than a class. */
export function scoreColor(v: number): string {
  if (v < 5) return "var(--red)";
  if (v <= 7) return "var(--amber)";
  return "var(--green)";
}
