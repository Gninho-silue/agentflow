import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, getClientId, resetClientIdForTests, wsUrl } from "./api";

const VALID = /^[A-Za-z0-9_-]{16,128}$/;

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetClientIdForTests();
});

describe("visitor id", () => {
  it("creates a valid id once and keeps it", () => {
    const first = getClientId();
    expect(first).toMatch(VALID);
    expect(window.localStorage.getItem("agentflow.clientId")).toBe(first);

    resetClientIdForTests();
    expect(getClientId()).toBe(first);
  });

  it("ignores a malformed stored value", () => {
    window.localStorage.setItem("agentflow.clientId", "bad id");
    expect(getClientId()).toMatch(VALID);
    expect(getClientId()).not.toBe("bad id");
  });

  it("still works when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const id = getClientId();
    expect(id).toMatch(VALID);
    expect(getClientId()).toBe(id);
    vi.restoreAllMocks();
  });
});

describe("apiFetch", () => {
  it("adds the visitor id to every API call", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]"));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/tasks", { method: "DELETE", headers: { "Content-Type": "application/json" } });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/tasks");
    const headers = new Headers(init.headers);
    expect(headers.get("X-Client-ID")).toBe(getClientId());
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.method).toBe("DELETE");
  });
});

describe("wsUrl", () => {
  it("passes the visitor id as a query parameter", () => {
    expect(wsUrl("t1")).toBe(`ws://localhost:8000/ws/t1?client_id=${getClientId()}`);
  });
});
