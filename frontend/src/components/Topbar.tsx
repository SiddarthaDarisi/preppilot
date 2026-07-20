"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useHealth } from "@/lib/health";
import { useTheme } from "@/lib/theme";
import SettingsDrawer from "@/components/SettingsDrawer";

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.56 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.65 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01A1.7 1.7 0 0 0 10.05 3V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01c.26.63.87 1.04 1.56 1.04H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51.94Z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M20.4 14.7A8.5 8.5 0 1 1 9.3 3.6a7 7 0 0 0 11.1 11.1Z" />
    </svg>
  );
}

/** PrepPilot mark — a soundwave in a gradient rounded square ("a coach that
 * hears you"). Gradient id is namespaced so multiple instances don't clash. */
function LogoMark() {
  return (
    <svg className="logo-mark" viewBox="0 0 32 32" width="32" height="32" aria-hidden="true">
      <defs>
        <linearGradient id="pp-logo-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--accent)" />
          <stop offset="1" stopColor="var(--purple)" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width="32" height="32" rx="9" fill="url(#pp-logo-grad)" />
      <g stroke="#fff" strokeWidth="2.4" strokeLinecap="round">
        <line x1="9" y1="13" x2="9" y2="19" />
        <line x1="13.5" y1="9.5" x2="13.5" y2="22.5" />
        <line x1="18.5" y1="7" x2="18.5" y2="25" />
        <line x1="23" y1="12" x2="23" y2="20" />
      </g>
    </svg>
  );
}

export default function Topbar() {
  const pathname = usePathname() || "/";
  const { health } = useHealth();
  const { theme, toggle } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const links = [
    { href: "/", label: "Home", active: pathname === "/" },
    { href: "/interview/", label: "Interview", active: pathname.startsWith("/interview") },
    { href: "/full-interview/", label: "Full Interview", active: pathname.startsWith("/full-interview") },
    { href: "/question-bank/", label: "Question bank", active: pathname.startsWith("/question-bank") },
    { href: "/dashboard/", label: "Dashboard", active: pathname.startsWith("/dashboard") },
  ];

  const degraded = health?.degraded ?? [];
  const isDegraded = degraded.length > 0;
  const pillLabel = health?.flags?.demo_llm
    ? `DEMO · ${health.llm_model}`
    : health
      ? `${health.llm_provider}/${health.llm_model} · stt:${health.stt_backend} · tts:${health.tts_backend}`
      : "";

  return (
    <header className="topbar">
      <Link href="/" className="brand">
        <LogoMark />
        <span>
          Prep<span className="brand-acc">Pilot</span>
        </span>
      </Link>
      {health && (
        <div
          className={"health-pill" + (isDegraded ? " degraded" : "")}
          title={isDegraded ? degraded.join("; ") : "All systems nominal"}
        >
          <span className="dot"></span>
          <span>{pillLabel}</span>
        </div>
      )}
      <div className="topbar-right">
        <button
          type="button"
          className="theme-toggle"
          onClick={() => setSettingsOpen(true)}
          title="Settings"
          aria-label="Open settings"
        >
          <GearIcon />
        </button>
        <button
          type="button"
          className="theme-toggle"
          onClick={toggle}
          title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          aria-label="Toggle color theme"
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
        <nav>
          {links.map((l) => (
            <Link key={l.href} href={l.href} className={l.active ? "active" : ""}>
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </header>
  );
}
