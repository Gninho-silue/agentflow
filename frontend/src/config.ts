/** Backend URLs, from VITE_API_BASE_URL (and optionally VITE_WS_BASE_URL). */

export function resolveApiBase(value: string | undefined): string {
  return (value || "http://localhost:8000").replace(/\/+$/, "");
}

/** The WebSocket URL follows the API URL unless set explicitly (https -> wss). */
export function resolveWsBase(value: string | undefined, apiBase: string): string {
  if (value) return value.replace(/\/+$/, "");
  return apiBase.replace(/^http/, "ws");
}

export const API_BASE = resolveApiBase(import.meta.env.VITE_API_BASE_URL);
export const WS_BASE = resolveWsBase(import.meta.env.VITE_WS_BASE_URL, API_BASE);
