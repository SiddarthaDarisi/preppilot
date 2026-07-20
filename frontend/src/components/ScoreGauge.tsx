"use client";

import { useEffect, useState } from "react";
import { scoreColor } from "@/lib/format";

/** Radial arc gauge for the session's overall score. Animates once on
 * mount (respecting prefers-reduced-motion) rather than looping. */
export default function ScoreGauge({
  value,
  max = 10,
  size = 128,
}: {
  value: number;
  max?: number;
  size?: number;
}) {
  const pct = Math.max(0, Math.min(1, value / max));
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const [animatedPct, setAnimatedPct] = useState(0);

  useEffect(() => {
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setAnimatedPct(pct);
      return;
    }
    let raf = 0;
    const duration = 700;
    const start = performance.now();
    const tick = (t: number) => {
      const elapsed = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - elapsed, 3);
      setAnimatedPct(pct * eased);
      if (elapsed < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [pct]);

  const dash = circumference * animatedPct;
  const color = scoreColor(value);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Overall score ${value.toFixed(1)} out of ${max}`}
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="var(--border)"
        strokeWidth={9}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={9}
        strokeLinecap="round"
        strokeDasharray={`${dash} ${circumference}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text
        x="50%"
        y="46%"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={size * 0.24}
        fontWeight={800}
        fill="var(--text)"
        fontFamily="var(--mono)"
      >
        {value.toFixed(1)}
      </text>
      <text
        x="50%"
        y="65%"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={size * 0.09}
        fill="var(--text-dim)"
      >
        / {max}
      </text>
    </svg>
  );
}
