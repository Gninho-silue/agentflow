import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TaskRecord, TaskResult } from "../types";
import { ResultViewer } from "./ResultViewer";

const API = "http://api.test";

function makeTask(result: Partial<TaskResult> = {}, overrides: Partial<TaskRecord> = {}): TaskRecord {
  return {
    task_id: "t1",
    task: "Analyze sales",
    file_path: null,
    status: "completed",
    error: null,
    created_at: "2026-11-21T00:00:00Z",
    updated_at: "2026-11-21T00:00:00Z",
    execution_time: 4.2,
    agents_used: ["planner", "code_agent", "reporter", "supervisor"],
    result: {
      task: "Analyze sales",
      subtasks: [],
      current_agent: "supervisor",
      file_data: null,
      code_output: "42",
      chart_path: null,
      report: "# Summary\n\nAll good.",
      status: "completed",
      error: null,
      messages: [],
      code_attempts: [{ attempt: 1, code: "print(6 * 7)", error: null, traceback: null, output: "42" }],
      agent_durations: { planner: 1.234, code_agent: 2.5, reporter: 0.4, supervisor: 0.001 },
      ...result,
    },
    ...overrides,
  };
}

describe("ResultViewer", () => {
  it("renders nothing without a task", () => {
    const { container } = render(<ResultViewer task={null} apiBase={API} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the generated code in a collapsible section", () => {
    render(<ResultViewer task={makeTask()} apiBase={API} />);
    const section = screen.getByText("Generated code").closest("details");
    expect(section).not.toBeNull();
    expect(section).not.toHaveAttribute("open");
    expect(section?.textContent).toContain("print(6 * 7)");
  });

  it("lists every self-correction attempt with its error and traceback", () => {
    const task = makeTask({
      code_attempts: [
        {
          attempt: 1,
          code: "print(1 / 0)",
          error: "division by zero",
          traceback: "ZeroDivisionError: division by zero",
          output: "",
        },
        { attempt: 2, code: "print(42)", error: null, traceback: null, output: "42" },
      ],
    });
    render(<ResultViewer task={task} apiBase={API} />);

    const attempts = screen.getByRole("list", { name: /code attempts/i });
    const items = within(attempts).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Attempt 1");
    expect(items[0]).toHaveTextContent("failed");
    expect(items[0]).toHaveTextContent("ZeroDivisionError: division by zero");
    expect(items[1]).toHaveTextContent("Attempt 2");
    expect(items[1]).toHaveTextContent("succeeded");
    // The code section shows the final version.
    expect(screen.getByText("Generated code").closest("details")?.textContent).toContain("print(42)");
  });

  it("hides the attempts list when the first attempt succeeded", () => {
    render(<ResultViewer task={makeTask()} apiBase={API} />);
    expect(screen.queryByRole("list", { name: /code attempts/i })).not.toBeInTheDocument();
  });

  it("loads chart images from the backend and drops foreign images", () => {
    const report =
      '# Report\n\n<img src="/uploads/chart_abc.png" alt="Analysis Chart" />\n\n![x](https://evil.example/x.png)';
    render(<ResultViewer task={makeTask({ report })} apiBase={API} />);

    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute("src", "http://api.test/uploads/chart_abc.png");
  });

  it("shows the duration of each agent", () => {
    render(<ResultViewer task={makeTask()} apiBase={API} />);
    const durations = screen.getByRole("list", { name: /duration per agent/i });
    expect(durations).toHaveTextContent("Planner1.2s");
    expect(durations).toHaveTextContent("CodeAgent2.5s");
    expect(durations).toHaveTextContent("Reporter0.4s");
    expect(durations).toHaveTextContent("Supervisor<0.1s");
  });

  it("copies the markdown report in one click", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    render(<ResultViewer task={makeTask()} apiBase={API} />);

    await user.click(screen.getByRole("button", { name: /copy/i }));

    expect(writeText).toHaveBeenCalledWith("# Summary\n\nAll good.");
    expect(await screen.findByRole("button", { name: /copied/i })).toBeInTheDocument();
  });

  it("keeps the markdown download", () => {
    render(<ResultViewer task={makeTask()} apiBase={API} />);
    expect(screen.getByRole("button", { name: /download/i })).toBeEnabled();
  });

  it("shows the error of a failed task", () => {
    render(<ResultViewer task={makeTask({ report: null }, { status: "error", error: "planner exploded" })} apiBase={API} />);
    expect(screen.getByText("planner exploded")).toBeInTheDocument();
  });
});
