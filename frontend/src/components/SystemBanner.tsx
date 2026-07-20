import { useHealth } from "@/lib/health";

/**
 * Persistent (non-dismissible, non-toast) degradation banners. Toasts are
 * for one-off events; these reflect ongoing server state and should stay
 * visible for as long as that state holds — a demo-mode session or a
 * voice-disabled server isn't a "moment", it's the whole session.
 */
export default function SystemBanner({ mode }: { mode?: "text" | "voice" }) {
  const { health } = useHealth();
  if (!health) return null;
  const flags = health.flags;

  const banners: React.ReactNode[] = [];

  if (flags?.demo_llm) {
    banners.push(
      <div className="sys-banner demo" role="status" key="demo">
        <span className="ico">⚠</span>
        <span>
          <strong>Demo mode</strong> — the local LLM is unreachable, so questions, feedback and
          every score are canned samples. Start Ollama and relaunch with run.ps1 for real
          coaching.
        </span>
      </div>,
    );
  }

  const voiceUnavailable =
    !!flags?.stt_missing || !!flags?.vad_missing || health.stt_backend === "none";
  if (mode === "voice" && voiceUnavailable) {
    banners.push(
      <div className="sys-banner voice-off" role="alert" key="voice">
        <span className="ico">⚠</span>
        <span>
          <strong>Voice mode unavailable</strong> — speech recognition isn&rsquo;t loaded in this
          server process. Launch with run.ps1 (uses .venv), or answer in text mode.
        </span>
      </div>,
    );
  }

  if (banners.length === 0) return null;
  return <>{banners}</>;
}
