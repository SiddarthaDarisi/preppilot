"use client";

import { useCallback, useRef, useState } from "react";

export interface ToastItem {
  id: number;
  message: string;
  kind: "error" | "info" | "success";
}

export type ToastFn = (
  message: string,
  kind?: "error" | "info" | "success",
  timeoutMs?: number,
) => void;

/** Page-local toast state + emitter. */
export function useToasts(): {
  toasts: ToastItem[];
  toast: ToastFn;
  dismiss: (id: number) => void;
} {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback<ToastFn>(
    (message, kind = "error", timeoutMs = 8000) => {
      const id = nextId.current++;
      setToasts((prev) => [...prev, { id, message, kind }]);
      if (timeoutMs) {
        setTimeout(() => dismiss(id), timeoutMs);
      }
    },
    [dismiss],
  );

  return { toasts, toast, dismiss };
}

export function ToastHost({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div className="toast-host">
      {toasts.map((t) => (
        <div key={t.id} className={"toast" + (t.kind !== "error" ? " " + t.kind : "")}>
          <span className="msg">{t.message}</span>
          <button className="close-x" onClick={() => onDismiss(t.id)}>
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
