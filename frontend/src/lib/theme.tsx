"use client";

/**
 * Theme state: `data-theme="dark"|"light"` on <html>, driven by this
 * provider. Light is the app default (set before first paint by the inline
 * script in layout.tsx); the toggle itself is in-memory only and resets on
 * reload.
 *
 * Why not persist the toggle: localStorage is off-limits for this app (see
 * CLAUDE.md), and a cookie would be pointless here — this is a static
 * export with no per-request server render to read one, so its only reader
 * would be the same client JS that could just keep the value in memory.
 * That trades zero benefit for a new bit of cross-request state, so we
 * don't bother; the OS preference already gets it right for most visits.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type Theme = "dark" | "light";

interface ThemeContextValue {
  theme: Theme;
  toggle: () => void;
  /** Bumped every time the theme changes — canvas-drawing components can
   * depend on this to know when to re-read CSS variables and redraw. */
  version: number;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readInitialTheme(): Theme {
  // Light is the app default (user preference — see layout.tsx's init
  // script); the attribute it set before paint wins if present.
  if (typeof document === "undefined") return "light";
  const attr = document.documentElement.dataset.theme;
  if (attr === "light" || attr === "dark") return attr;
  return "light";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    setVersion((v) => v + 1);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  const value = useMemo(() => ({ theme, toggle, version }), [theme, toggle, version]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    // Components used outside the provider (shouldn't happen in practice)
    // still get a sane, non-crashing default.
    return { theme: "light", toggle: () => {}, version: 0 };
  }
  return ctx;
}
