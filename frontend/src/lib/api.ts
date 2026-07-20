/**
 * PrepPilot — API base helper.
 *
 * In `next dev` (port 3000) the FastAPI backend runs separately on
 * http://127.0.0.1:8000, so we point REST + WS there. In production the
 * static export is served by the FastAPI server itself, so everything is
 * same-origin (with ws/wss derived from the page protocol).
 */

function isNextDev(): boolean {
  return typeof window !== "undefined" && window.location.port === "3000";
}

/** Base URL for REST calls ('' means same-origin). */
export function apiBase(): string {
  return isNextDev() ? "http://127.0.0.1:8000" : "";
}

/** Base URL for WebSocket connections. */
export function wsBase(): string {
  if (typeof window === "undefined") return "";
  if (isNextDev()) return "ws://127.0.0.1:8000";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

/** GET a JSON endpoint; throws on non-2xx. */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(apiBase() + path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

/** POST a JSON body; throws on non-2xx. */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(apiBase() + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

/** PUT a JSON body; throws on non-2xx. */
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(apiBase() + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

/** DELETE a resource; throws on non-2xx. */
export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(apiBase() + path, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}
