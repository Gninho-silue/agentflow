import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getClientId } from "../api";
import type { TaskRecord } from "../types";
import { TaskHistory } from "./TaskHistory";

const task = (id: string, status = "completed"): TaskRecord => ({
  task_id: id,
  task: `Task ${id}`,
  file_path: null,
  status,
  result: null,
  error: null,
  created_at: "2026-11-21T00:00:00Z",
  updated_at: "2026-11-21T00:00:00Z",
  execution_time: 1,
  agents_used: [],
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function setup(tasks: TaskRecord[]) {
  const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const props = {
    selectedTaskId: null,
    tasks,
    onSelect: vi.fn(),
    onTaskDeleted: vi.fn(),
    onAllTasksDeleted: vi.fn(),
  };
  render(<TaskHistory {...props} />);
  return { fetchMock, props };
}

describe("TaskHistory", () => {
  it("explains that the history belongs to this browser when empty", () => {
    setup([]);
    expect(screen.getByText(/only you see them/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /clear all/i })).not.toBeInTheDocument();
  });

  it("puts Clear all next to the heading", () => {
    setup([task("a")]);
    const header = screen.getByRole("heading", { name: /recent tasks/i }).parentElement as HTMLElement;
    expect(within(header).getByRole("button", { name: /clear all/i })).toBeInTheDocument();
  });

  it("deletes one task with the visitor id", async () => {
    const { fetchMock, props } = setup([task("a"), task("b")]);
    await userEvent.click(screen.getAllByRole("button", { name: /delete task/i })[1]);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/tasks\/b$/);
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get("X-Client-ID")).toBe(getClientId());
    expect(props.onTaskDeleted).toHaveBeenCalledWith("b");
  });

  it("clears my history after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { fetchMock, props } = setup([task("a")]);
    await userEvent.click(screen.getByRole("button", { name: /clear all/i }));

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/tasks$/);
    expect(new Headers(init.headers).get("X-Client-ID")).toBe(getClientId());
    expect(props.onAllTasksDeleted).toHaveBeenCalled();
  });

  it("does nothing when Clear all is cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { fetchMock } = setup([task("a")]);
    await userEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
