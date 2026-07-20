/**
 * Reads the current theme's chart colors from CSS custom properties, so
 * hand-rolled canvas charts stay in sync with the dark/light toggle instead
 * of hardcoding hex values (the old dashboard/page.tsx PALETTE + hardcoded
 * rgba() calls in TrendsChart both had to change per-theme by hand).
 */

export interface ChartColors {
  series: string[];
  grid: string;
  axisText: string;
  tooltipBg: string;
  tooltipBorder: string;
  text: string;
}

const FALLBACK: ChartColors = {
  series: ["#5b8cff", "#34c98e", "#f0b13d", "#a78bfa", "#4dd0e1", "#f2607a", "#9aa3b5"],
  grid: "rgba(255,255,255,0.07)",
  axisText: "#6b7488",
  tooltipBg: "#151a26",
  tooltipBorder: "#2e3650",
  text: "#e6e9f0",
};

export function getChartColors(): ChartColors {
  if (typeof window === "undefined") return FALLBACK;
  const styles = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => {
    const val = styles.getPropertyValue(name).trim();
    return val || fallback;
  };
  return {
    series: [
      v("--chart-1", FALLBACK.series[0]),
      v("--chart-2", FALLBACK.series[1]),
      v("--chart-3", FALLBACK.series[2]),
      v("--chart-4", FALLBACK.series[3]),
      v("--chart-5", FALLBACK.series[4]),
      v("--chart-6", FALLBACK.series[5]),
      v("--chart-7", FALLBACK.series[6]),
    ],
    grid: v("--chart-grid", FALLBACK.grid),
    axisText: v("--chart-axis-text", FALLBACK.axisText),
    tooltipBg: v("--chart-tooltip-bg", FALLBACK.tooltipBg),
    tooltipBorder: v("--chart-tooltip-border", FALLBACK.tooltipBorder),
    text: v("--text", FALLBACK.text),
  };
}
