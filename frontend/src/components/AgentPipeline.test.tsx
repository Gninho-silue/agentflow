import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentProgress } from "../types";
import { AgentPipeline } from "./AgentPipeline";

const agents: AgentProgress[] = [
  { agent: "planner", status: "done", message: "Planned 3 subtasks." },
  { agent: "file_agent", status: "skipped", message: "Not needed for this task." },
  { agent: "code_agent", status: "running", message: "Attempt 1 failed. Retrying..." },
  { agent: "reporter", status: "idle", message: "Report not generated yet." },
  { agent: "supervisor", status: "error", message: "Stopped." },
];

describe("AgentPipeline", () => {
  it("lists the five agents in order with a readable state for each", () => {
    render(<AgentPipeline agents={agents} connected />);
    const steps = within(screen.getByRole("list", { name: /agent pipeline/i })).getAllByRole("listitem");

    expect(steps.map((step) => step.querySelector("h3")?.textContent)).toEqual([
      "Planner",
      "FileAgent",
      "CodeAgent",
      "Reporter",
      "Supervisor",
    ]);
    // States are written out, not conveyed by color alone.
    expect(steps[0]).toHaveTextContent("Done");
    expect(steps[1]).toHaveTextContent("Skipped");
    expect(steps[2]).toHaveTextContent("Running");
    expect(steps[3]).toHaveTextContent("Waiting");
    expect(steps[4]).toHaveTextContent("Failed");
    expect(steps[2]).toHaveAttribute("aria-current", "step");
  });

  it("summarizes the run in the heading", () => {
    const { rerender } = render(<AgentPipeline agents={agents} connected />);
    expect(screen.getByText("Running")).toBeInTheDocument();

    const idle = agents.map((agent) => ({ ...agent, status: "idle" as const }));
    rerender(<AgentPipeline agents={idle} connected={false} />);
    expect(screen.getByText("Waiting for a task")).toBeInTheDocument();
  });
});
