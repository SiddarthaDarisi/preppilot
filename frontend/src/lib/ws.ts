/**
 * Interview WebSocket connection manager with auto-reconnect.
 *
 * The backend now supports resuming an in-progress session (see
 * backend/orchestrator.py `resume()` + the `resumed` WS message) instead of
 * restarting it, so a dropped connection (e.g. the keepalive-timeout 1011
 * that motivated this — see CLAUDE.md) can recover instead of stranding the
 * user. This module owns reconnect/backoff; the caller only sees connection
 * state changes and parsed messages.
 */

import { wsBase } from "@/lib/api";
import type { ServerMessage } from "@/lib/types";

export type ConnectionState =
  | "connecting"
  | "open"
  | "reconnecting"
  | "disconnected"
  | "closed";

export interface SocketManagerHandlers {
  onMessage: (msg: ServerMessage) => void;
  /** attempt is only meaningful for "reconnecting". */
  onStateChange: (state: ConnectionState, attempt?: number) => void;
}

export interface SocketManager {
  sendBinary: (data: ArrayBufferLike) => void;
  sendJson: (obj: Record<string, unknown>) => void;
  /** Manually retry immediately after landing in "disconnected". */
  retryNow: () => void;
  /** Call once the interview is over (report received) or the user leaves —
   * closes the socket and disables any further reconnect attempts. */
  stop: () => void;
  getState: () => ConnectionState;
}

const BACKOFF_SCHEDULE_MS = [1000, 2000, 4000, 8000, 15000, 15000];
const MAX_ATTEMPTS = BACKOFF_SCHEDULE_MS.length;

export function createInterviewSocket(
  sessionId: number,
  handlers: SocketManagerHandlers,
): SocketManager {
  let ws: WebSocket | null = null;
  let state: ConnectionState = "connecting";
  let attempt = 0;
  let stopped = false;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const setState = (s: ConnectionState, a?: number) => {
    state = s;
    handlers.onStateChange(s, a);
  };

  const clearRetryTimer = () => {
    if (retryTimer !== null) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (stopped) return;
    if (attempt >= MAX_ATTEMPTS) {
      setState("disconnected");
      return;
    }
    const base = BACKOFF_SCHEDULE_MS[attempt];
    const jitter = base * 0.2 * (Math.random() - 0.5); // ±10%
    attempt += 1;
    setState("reconnecting", attempt);
    clearRetryTimer();
    retryTimer = setTimeout(connect, Math.max(250, base + jitter));
  };

  function connect() {
    if (stopped) return;
    clearRetryTimer();
    const socket = new WebSocket(`${wsBase()}/ws/session/${sessionId}`);
    socket.binaryType = "arraybuffer";
    ws = socket;

    socket.addEventListener("open", () => {
      attempt = 0;
      setState("open");
    });

    socket.addEventListener("message", (e: MessageEvent) => {
      if (typeof e.data !== "string") return; // server never sends binary
      let msg: ServerMessage;
      try {
        msg = JSON.parse(e.data) as ServerMessage;
      } catch {
        return;
      }
      handlers.onMessage(msg);
    });

    socket.addEventListener("close", () => {
      if (stopped) {
        setState("closed");
        return;
      }
      scheduleReconnect();
    });

    // "error" is always followed by "close" for browser WebSockets — no
    // separate handling needed beyond letting close() drive the reconnect.
    socket.addEventListener("error", () => {});
  }

  connect();

  return {
    sendBinary(data) {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
    },
    sendJson(obj) {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    },
    retryNow() {
      if (stopped) return;
      attempt = 0;
      clearRetryTimer();
      setState("connecting");
      connect();
    },
    stop() {
      stopped = true;
      clearRetryTimer();
      if (ws) {
        ws.close();
      }
      setState("closed");
    },
    getState: () => state,
  };
}
