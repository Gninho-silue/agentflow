import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TaskRecord } from "../types";
import { useWebSocket } from "./useWebSocket";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    act(() => this.onopen?.());
  }

  receive(payload: unknown): void {
    act(() => this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>));
  }
}

function latestSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  if (!socket) throw new Error("No WebSocket was opened");
  return socket;
}

function update(agent: string, status: string, message = `${agent} ${status}`) {
  return { type: "agent_update", agent, status, message, timestamp: "2026-11-21T00:00:00Z" };
}

function statusOf(result: { current: ReturnType<typeof useWebSocket> }) {
  return Object.fromEntries(result.current.agents.map((a) => [a.agent, a.status]));
}

const taskRecord = (status: string): TaskRecord => ({
  task_id: "t1",
  task: "Analyze",
  file_path: null,
  status,
  result: null,
  error: status === "error" ? "boom" : null,
  created_at: "2026-11-21T00:00:00Z",
  updated_at: "2026-11-21T00:00:00Z",
  execution_time: 1.2,
  agents_used: ["planner", "supervisor"],
});

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useWebSocket", () => {
  it("does not connect without a task id and starts with every agent idle", () => {
    const { result } = renderHook(() => useWebSocket(null));

    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(result.current.connected).toBe(false);
    expect(result.current.task).toBeNull();
    expect(new Set(Object.values(statusOf(result)))).toEqual(new Set(["idle"]));
  });

  it("connects to /ws/{taskId} and tracks the connection state", () => {
    const { result } = renderHook(() => useWebSocket("t1"));
    const socket = latestSocket();

    expect(socket.url).toMatch(/\/ws\/t1$/);
    socket.open();
    expect(result.current.connected).toBe(true);
  });

  it("marks the updated agent and moves earlier running agents to done", () => {
    const { result } = renderHook(() => useWebSocket("t1"));
    const socket = latestSocket();

    socket.receive(update("planner", "running", "Planner created subtasks"));
    expect(statusOf(result).planner).toBe("running");
    expect(result.current.agents[0].message).toBe("Planner created subtasks");

    socket.receive(update("code_agent", "running"));
    expect(statusOf(result)).toMatchObject({
      planner: "done",
      file_agent: "idle",
      code_agent: "running",
    });
  });

  it("maps unknown agent names to the planner and unknown statuses to idle", () => {
    const { result } = renderHook(() => useWebSocket("t1"));
    const socket = latestSocket();

    socket.receive(update("created", "idle", "Task created."));
    expect(result.current.agents[0]).toMatchObject({ agent: "planner", status: "idle", message: "Task created." });
  });

  it("marks agents that ran as done and the others as skipped when the task completes", () => {
    const { result } = renderHook(() => useWebSocket("t1"));
    const socket = latestSocket();
    socket.open();

    socket.receive(update("planner", "running"));
    socket.receive(update("code_agent", "running"));
    socket.receive(update("reporter", "running"));
    socket.receive(update("supervisor", "completed"));
    socket.receive({ type: "task", task: taskRecord("completed") });

    expect(result.current.task?.status).toBe("completed");
    expect(statusOf(result)).toEqual({
      planner: "done",
      file_agent: "skipped",
      code_agent: "done",
      reporter: "done",
      supervisor: "done",
    });
    expect(result.current.agents[1].message).toBe("Not needed for this task.");
    expect(result.current.connected).toBe(false);
  });

  it("marks only the running agent as error when the task fails", () => {
    const { result } = renderHook(() => useWebSocket("t1"));
    const socket = latestSocket();

    socket.receive(update("planner", "running"));
    socket.receive(update("code_agent", "running"));
    socket.receive({ type: "complete", status: "error" });

    expect(statusOf(result)).toMatchObject({
      planner: "done",
      file_agent: "idle",
      code_agent: "error",
      reporter: "idle",
    });
  });

  it("collects code attempts and shows retries on the code agent", () => {
    const { result } = renderHook(() => useWebSocket("t1"));
    const socket = latestSocket();

    socket.receive({
      type: "code_attempt",
      agent: "code_agent",
      attempt: 1,
      code: "print(1 / 0)",
      error: "division by zero",
      traceback: "ZeroDivisionError: division by zero",
      status: "error",
      timestamp: "2026-11-21T00:00:00Z",
    });

    expect(result.current.attempts).toEqual([
      { attempt: 1, code: "print(1 / 0)", error: "division by zero", traceback: "ZeroDivisionError: division by zero" },
    ]);
    const codeAgent = result.current.agents.find((a) => a.agent === "code_agent");
    expect(codeAgent).toMatchObject({ status: "running", message: "Attempt 1 failed: division by zero. Retrying..." });

    socket.receive({
      type: "code_attempt",
      agent: "code_agent",
      attempt: 2,
      code: "print(42)",
      error: null,
      traceback: null,
      status: "completed",
      timestamp: "2026-11-21T00:00:01Z",
    });

    expect(result.current.attempts.map((a) => a.attempt)).toEqual([1, 2]);
    expect(result.current.agents.find((a) => a.agent === "code_agent")?.message).toBe("Attempt 2 succeeded.");
  });

  it("takes the attempts from the final task record", () => {
    const { result } = renderHook(() => useWebSocket("t1"));
    const record = taskRecord("completed");
    record.result = {
      task: "Analyze",
      subtasks: [],
      current_agent: "supervisor",
      file_data: null,
      code_output: "42",
      chart_path: null,
      report: "# Report",
      status: "completed",
      error: null,
      messages: [],
      code_attempts: [{ attempt: 1, code: "print(42)", error: null, traceback: null, output: "42" }],
    };

    latestSocket().receive({ type: "task", task: record });

    expect(result.current.attempts).toEqual([{ attempt: 1, code: "print(42)", error: null, traceback: null }]);
  });

  it("resets state and closes the old socket when the task id changes", () => {
    const { result, rerender } = renderHook(({ id }) => useWebSocket(id), {
      initialProps: { id: "t1" as string | null },
    });
    const first = latestSocket();
    first.receive({ type: "task", task: taskRecord("completed") });

    rerender({ id: "t2" });

    expect(first.closed).toBe(true);
    expect(latestSocket().url).toMatch(/\/ws\/t2$/);
    expect(result.current.task).toBeNull();
    expect(new Set(Object.values(statusOf(result)))).toEqual(new Set(["idle"]));
  });
});
