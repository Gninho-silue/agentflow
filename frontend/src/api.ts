import { API_BASE, WS_BASE } from "./config";

/**
 * Each browser gets a random visitor id, sent with every API call. The backend
 * only shows a visitor their own tasks. Kept in localStorage so history
 * survives reloads; falls back to memory when storage is blocked.
 */
const STORAGE_KEY = "agentflow.clientId";
const VALID_ID = /^[A-Za-z0-9_-]{16,128}$/;

let cachedId: string | null = null;

function randomId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function getClientId(): string {
  if (cachedId) return cachedId;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && VALID_ID.test(stored)) {
      cachedId = stored;
      return stored;
    }
  } catch {
    // Storage blocked (private mode, strict settings): keep the id in memory.
  }
  cachedId = randomId();
  try {
    window.localStorage.setItem(STORAGE_KEY, cachedId);
  } catch {
    // Same as above.
  }
  return cachedId;
}

export function resetClientIdForTests(): void {
  cachedId = null;
}

/** fetch() against the API with the visitor id header. `path` starts with "/". */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-Client-ID", getClientId());
  return fetch(`${API_BASE}${path}`, { ...init, headers });
}

/** WebSocket URL for a task; browsers cannot set headers on WebSockets. */
export function wsUrl(taskId: string): string {
  return `${WS_BASE}/ws/${taskId}?client_id=${encodeURIComponent(getClientId())}`;
}
