import { useCallback, useEffect, useRef, useState } from "react";

/**
 * - checking: first request in flight
 * - waking:   no answer yet; free hosting may be starting the server
 * - online:   /health answered
 * - offline:  still no answer after the waiting budget
 */
export type BackendStatus = "checking" | "waking" | "online" | "offline";

interface Options {
  retryMs?: number;
  giveUpMs?: number;
}

export function useBackendStatus(
  apiBase: string,
  { retryMs = 3000, giveUpMs = 75000 }: Options = {},
): { status: BackendStatus; retry: () => void } {
  const [status, setStatus] = useState<BackendStatus>("checking");
  const [attempt, setAttempt] = useState(0);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    const startedAt = Date.now();
    let timer: number | undefined;

    const probe = async () => {
      try {
        const response = await fetch(`${apiBase}/health`, { cache: "no-store" });
        if (cancelled.current) return;
        if (response.ok) {
          setStatus("online");
          return;
        }
      } catch {
        if (cancelled.current) return;
      }
      if (Date.now() - startedAt >= giveUpMs) {
        setStatus("offline");
        return;
      }
      setStatus("waking");
      timer = window.setTimeout(() => void probe(), retryMs);
    };

    setStatus("checking");
    void probe();
    return () => {
      cancelled.current = true;
      window.clearTimeout(timer);
    };
  }, [apiBase, retryMs, giveUpMs, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { status, retry };
}
