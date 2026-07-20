"use client";

/**
 * Shared /api/health state. Fetched once and made available app-wide via
 * context, so every page (Topbar's health pill, degradation banners, the
 * setup form's voice-mode toggle) sees the same snapshot without each
 * re-fetching independently.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";
import type { HealthInfo } from "@/lib/types";

interface HealthContextValue {
  health: HealthInfo | null;
  refresh: () => void;
}

const HealthContext = createContext<HealthContextValue | null>(null);

export function HealthProvider({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiGet<HealthInfo>("/api/health")
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch(() => {
        /* backend not up yet — stays null, callers treat that as "unknown" */
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const value = useMemo(() => ({ health, refresh }), [health, refresh]);

  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

export function useHealth(): HealthContextValue {
  const ctx = useContext(HealthContext);
  if (!ctx) return { health: null, refresh: () => {} };
  return ctx;
}
