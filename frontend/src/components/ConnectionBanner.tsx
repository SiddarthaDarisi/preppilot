import type { ConnectionState } from "@/lib/ws";

/** Shown above the interview panel whenever the socket isn't cleanly open. */
export default function ConnectionBanner({
  state,
  attempt,
  onRetry,
}: {
  state: ConnectionState;
  attempt?: number;
  onRetry: () => void;
}) {
  if (state === "open" || state === "closed" || state === "connecting") return null;

  if (state === "reconnecting") {
    return (
      <div className="conn-banner">
        <span className="spinner" />
        <span className="msg">
          Connection dropped — reconnecting{attempt ? ` (attempt ${attempt})` : ""}…
        </span>
      </div>
    );
  }

  return (
    <div className="conn-banner disconnected">
      <span className="msg">
        Lost connection to the backend — is it still running?
      </span>
      <button className="btn" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
