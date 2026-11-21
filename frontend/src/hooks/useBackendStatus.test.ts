import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBackendStatus } from "./useBackendStatus";

const ok = () => Promise.resolve(new Response('{"status":"ok"}', { status: 200 }));
const down = () => Promise.reject(new TypeError("Failed to fetch"));

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useBackendStatus", () => {
  it("is online when /health answers", async () => {
    const fetchMock = vi.fn(ok);
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus("http://api"));

    expect(result.current.status).toBe("checking");
    await flush();
    expect(result.current.status).toBe("online");
    expect(fetchMock).toHaveBeenCalledWith("http://api/health", expect.anything());
  });

  it("reports a waking server, then online once it answers", async () => {
    const fetchMock = vi.fn().mockImplementationOnce(down).mockImplementationOnce(down).mockImplementation(ok);
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus("http://api", { retryMs: 1000, giveUpMs: 60000 }));

    await flush();
    expect(result.current.status).toBe("waking");
    await flush(1000);
    expect(result.current.status).toBe("waking");
    await flush(1000);
    expect(result.current.status).toBe("online");
  });

  it("gives up and reports offline after the waiting budget", async () => {
    vi.stubGlobal("fetch", vi.fn(down));
    const { result } = renderHook(() => useBackendStatus("http://api", { retryMs: 1000, giveUpMs: 3000 }));

    await flush(3500);
    expect(result.current.status).toBe("offline");
  });

  it("can retry after going offline", async () => {
    const fetchMock = vi.fn<() => Promise<Response>>(down);
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useBackendStatus("http://api", { retryMs: 1000, giveUpMs: 1000 }));
    await flush(1500);
    expect(result.current.status).toBe("offline");

    fetchMock.mockImplementation(ok);
    act(() => result.current.retry());
    await flush();
    expect(result.current.status).toBe("online");
  });
});
