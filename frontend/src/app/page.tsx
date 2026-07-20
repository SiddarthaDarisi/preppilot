"use client";

/**
 * PrepPilot — Home. Product landing: hero, quick-start (resume the last
 * session's role via /api/sessions — the server is the memory, no
 * localStorage), and a feature grid. The live interview flow lives at
 * /interview.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { SessionSummary, StatsResult } from "@/lib/types";
import SystemBanner from "@/components/SystemBanner";

interface RandomQuestion {
  id: number;
  text: string;
  category: string;
  role: string;
  seniority: string;
}

/** Consecutive days (ending today or yesterday — a one-day grace period)
 * with at least one session, computed client-side from session dates. */
function computeStreak(sessions: SessionSummary[]): number {
  if (!sessions.length) return 0;
  const days = new Set(sessions.map((s) => new Date(s.created_at).toDateString()));
  const cursor = new Date();
  if (!days.has(cursor.toDateString())) {
    cursor.setDate(cursor.getDate() - 1);
    if (!days.has(cursor.toDateString())) return 0;
  }
  let streak = 0;
  while (days.has(cursor.toDateString())) {
    streak++;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

const FEATURES: { icon: string; title: string; body: string }[] = [
  {
    icon: "🎙️",
    title: "Voice-first practice",
    body: "Answer out loud; Whisper transcribes locally so nothing leaves your machine.",
  },
  {
    icon: "⚡",
    title: "Instant delivery alerts",
    body: "Pace, fillers, pauses and monotone flagged in seconds — before the coach even replies.",
  },
  {
    icon: "🎯",
    title: "STAR coaching",
    body: "Every answer scored 1–10 across content, structure, specificity and delivery, with concrete fixes.",
  },
  {
    icon: "📈",
    title: "Progress you can see",
    body: "Score trends, filler habits and full session history across every practice run.",
  },
];

export default function HomePage() {
  const [last, setLast] = useState<SessionSummary | null>(null);
  const [streak, setStreak] = useState(0);
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [qotd, setQotd] = useState<RandomQuestion | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<SessionSummary[]>("/api/sessions")
      .then((s) => {
        if (cancelled) return;
        if (s.length > 0) setLast(s[0]);
        setStreak(computeStreak(s));
      })
      .catch(() => {
        /* no backend / no history — quick-start simply doesn't render */
      });
    apiGet<StatsResult>("/api/stats")
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch(() => {
        /* readiness tile is optional — hide it silently on failure */
      });
    apiGet<{ question: RandomQuestion | null }>("/api/question-bank/random")
      .then((r) => {
        if (!cancelled) setQotd(r.question);
      })
      .catch(() => {
        /* question-of-the-day is optional — hide it silently on failure */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const resumeHref = last
    ? `/interview/?role=${encodeURIComponent(last.role)}&seniority=${last.seniority}`
    : "/interview/";
  const qotdHref = qotd
    ? `/interview/?mode=drill&bank_ids=${qotd.id}&role=${encodeURIComponent(qotd.role)}&seniority=${qotd.seniority}`
    : "";

  return (
    <>
      <SystemBanner />

      <section className="hero">
        <h1 className="hero-title">Practice interviews with an AI coach that hears you</h1>
        <p className="hero-sub">
          PrepPilot runs a tailored mock interview, transcribes your voice, scores every answer
          against a STAR rubric, and coaches your pace, fillers and tone — fully local, fully
          private.
        </p>
        <div className="actions-row">
          <Link href="/interview/" className="btn primary lg">
            Start an interview
          </Link>
          <Link href="/dashboard/" className="btn ghost lg">
            View progress
          </Link>
        </div>
      </section>

      {(stats?.readiness_score != null || streak > 0) && (
        <div className="stat-tiles home-tiles">
          {stats?.readiness_score != null && (
            <div className="stat-tile">
              <div className="lbl">Interview readiness</div>
              <div className="val-row">
                <span className="val">{Math.round(stats.readiness_score)}</span>
                <span className="sub" style={{ marginTop: 0 }}>/100</span>
              </div>
              <div className="sub">last 5 sessions — score, confidence &amp; expressiveness</div>
            </div>
          )}
          {streak > 0 && (
            <div className="stat-tile streak-tile">
              <div className="lbl">Practice streak</div>
              <div className="val-row">
                <span className="streak-flame">🔥</span>
                <span className="val">{streak}</span>
              </div>
              <div className="sub">day{streak === 1 ? "" : "s"} in a row</div>
            </div>
          )}
        </div>
      )}

      {last && (
        <section className="card quickstart">
          <h2>Pick up where you left off</h2>
          <p className="subtitle">
            Your last session was {last.role} ({last.seniority}).
          </p>
          <Link href={resumeHref} className="btn primary">
            Practice again as {last.role} ({last.seniority})
          </Link>
        </section>
      )}

      {qotd && (
        <section className="card qotd-card">
          <h2>Question of the day</h2>
          <p className="subtitle">{qotd.text}</p>
          <Link href={qotdHref} className="btn primary">
            Answer this →
          </Link>
        </section>
      )}

      <section className="feature-grid">
        {FEATURES.map((f) => (
          <div className="feature-card" key={f.title}>
            <div className="feature-icon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </section>
    </>
  );
}
