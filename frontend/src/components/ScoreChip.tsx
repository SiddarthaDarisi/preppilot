import { scoreClass } from "@/lib/format";

/** One colored score chip (red < 5, amber 5-7, green > 7). */
export default function ScoreChip({
  label,
  value,
  digits = 0,
  overall = false,
}: {
  label?: string;
  value: number;
  digits?: number;
  overall?: boolean;
}) {
  return (
    <span
      className={
        "score-chip " + scoreClass(value) + (overall ? " s-overall" : "")
      }
    >
      {label !== undefined && <span>{label}</span>}
      <b>{digits > 0 ? value.toFixed(digits) : String(value)}</b>
    </span>
  );
}
