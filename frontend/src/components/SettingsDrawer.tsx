"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import type { AppSettings } from "@/lib/types";

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
      <polygon points="7 4 20 12 7 20" />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="spin" aria-hidden="true">
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}

/** Settings sheet (topbar gear). Settings persist server-side (the static
 * export has no localStorage) and apply immediately — even mid-interview,
 * since the backend reads the voice per synthesis call. */
export default function SettingsDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const previewCacheRef = useRef<Map<string, string>>(new Map());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (!open || fetchedRef.current) return;
    fetchedRef.current = true;
    apiGet<AppSettings>("/api/settings")
      .then(setSettings)
      .catch(() => setLoadError(true));
  }, [open]);

  // Close on Escape (same behavior as the session-detail drawer).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const selectVoice = useCallback(
    async (voiceId: string) => {
      if (!settings || voiceId === settings.tts_voice || saving) return;
      setSaving(true);
      try {
        await apiPut<{ tts_voice: string }>("/api/settings", { tts_voice: voiceId });
        setSettings((s) => (s ? { ...s, tts_voice: voiceId } : s));
        setSavedFlash(true);
        setTimeout(() => setSavedFlash(false), 2000);
      } catch {
        /* selection stays as-is; the card simply doesn't move */
      } finally {
        setSaving(false);
      }
    },
    [settings, saving],
  );

  const playPreview = useCallback(async (voiceId: string) => {
    if (audioRef.current) audioRef.current.pause();
    const cached = previewCacheRef.current.get(voiceId);
    if (cached) {
      const audio = new Audio("data:audio/wav;base64," + cached);
      audioRef.current = audio;
      audio.play().catch(() => {});
      return;
    }
    setPreviewing(voiceId);
    try {
      const res = await apiPost<{ audio_b64: string | null }>("/api/settings/voice-preview", {
        voice: voiceId,
      });
      if (!res.audio_b64) {
        setPreviewUnavailable(true);
        return;
      }
      previewCacheRef.current.set(voiceId, res.audio_b64);
      const audio = new Audio("data:audio/wav;base64," + res.audio_b64);
      audioRef.current = audio;
      audio.play().catch(() => {});
    } catch {
      setPreviewUnavailable(true);
    } finally {
      setPreviewing(null);
    }
  }, []);

  const ttsOff = settings?.tts_backend === "none";

  return (
    <>
      <div className={"drawer-overlay" + (open ? " open" : "")} onClick={onClose}></div>
      <aside className={"detail-drawer settings-drawer" + (open ? " open" : "")}>
        <div className="drawer-header">
          <h3>Settings</h3>
          <div className="settings-header-right">
            {savedFlash && <span className="saved-flash">Saved ✓</span>}
            <button className="btn ghost" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        <div className="drawer-body">
          <div className="fb-section-title">Interviewer voice</div>
          <p className="subtitle" style={{ marginBottom: 12 }}>
            Applies immediately, everywhere. Audio is cached per voice, so questions you&rsquo;ve
            heard before in a voice replay instantly when you switch back to it.
          </p>

          {loadError && (
            <div className="empty-state">Could not load settings — is the backend running?</div>
          )}
          {!settings && !loadError && (
            <div>
              {[0, 1, 2].map((i) => (
                <div className="skeleton skeleton-row" key={i} style={{ height: 56 }} />
              ))}
            </div>
          )}

          {settings && (
            <div className="voice-list" role="radiogroup" aria-label="Interviewer voice">
              {settings.voices.map((v) => {
                const selected = v.id === settings.tts_voice;
                return (
                  <div
                    className={"voice-option" + (selected ? " selected" : "")}
                    key={v.id}
                    role="radio"
                    aria-checked={selected}
                    tabIndex={0}
                    onClick={() => selectVoice(v.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        selectVoice(v.id);
                      }
                    }}
                  >
                    <div className="voice-radio" aria-hidden="true" />
                    <div className="voice-info">
                      <div className="voice-name">{v.label}</div>
                      <div className="voice-desc">{v.description}</div>
                    </div>
                    <button
                      type="button"
                      className="voice-preview-btn"
                      title={"Hear " + v.label}
                      aria-label={"Preview voice " + v.label}
                      disabled={previewing !== null || ttsOff}
                      onClick={(e) => {
                        e.stopPropagation();
                        playPreview(v.id);
                      }}
                    >
                      {previewing === v.id ? <SpinnerIcon /> : <PlayIcon />}
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {(ttsOff || previewUnavailable) && (
            <p className="hint-text">
              {ttsOff
                ? "Voice output is turned off in config (tts.backend: none) — the selection is saved for when it's re-enabled."
                : "Preview needs the voice stack loaded in this server process — launch with run.ps1. Your selection is still saved."}
            </p>
          )}
        </div>
      </aside>
    </>
  );
}
