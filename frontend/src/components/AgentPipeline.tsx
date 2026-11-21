import { Check, Loader2, Minus, X } from "lucide-react";
import type { AgentName, AgentProgress, AgentStatus } from "../types";

interface AgentPipelineProps {
  agents: AgentProgress[];
  connected: boolean;
}

const labels: Record<AgentName, string> = {
  planner: "Planner",
  file_agent: "FileAgent",
  code_agent: "CodeAgent",
  reporter: "Reporter",
  supervisor: "Supervisor",
};

const stateText: Record<AgentStatus, string> = {
  idle: "Waiting",
  running: "Running",
  done: "Done",
  error: "Failed",
  skipped: "Skipped",
};

const stateColor: Record<AgentStatus, string> = {
  idle: "text-ink-faint",
  running: "text-accent",
  done: "text-ok",
  error: "text-bad",
  skipped: "text-ink-faint",
};

function summary(agents: AgentProgress[], connected: boolean): string {
  if (agents.some((agent) => agent.status === "error")) return "Stopped on an error";
  if (connected || agents.some((agent) => agent.status === "running")) return "Running";
  if (agents.every((agent) => agent.status === "done" || agent.status === "skipped")) return "Finished";
  return "Waiting for a task";
}

export function AgentPipeline({ agents, connected }: AgentPipelineProps): JSX.Element {
  return (
    <section aria-labelledby="pipeline-title" className="rounded-xl border border-line bg-surface p-5">
      <div className="mb-5 flex items-baseline justify-between gap-3">
        <h2 id="pipeline-title" className="text-[15px] font-semibold text-ink">
          Pipeline
        </h2>
        <p className="text-xs text-ink-soft" aria-live="polite">
          {summary(agents, connected)}
        </p>
      </div>

      {/* A real sequence: vertical track on small screens, horizontal from lg. */}
      <ol aria-label="Agent pipeline" className="grid gap-0 lg:grid-cols-5 lg:gap-3">
        {agents.map((agent, index) => {
          const last = index === agents.length - 1;
          const reached = agent.status === "done" || agent.status === "skipped";
          return (
            <li
              key={agent.agent}
              aria-current={agent.status === "running" ? "step" : undefined}
              className="relative flex gap-3 pb-5 last:pb-0 lg:flex-col lg:gap-3 lg:pb-0"
            >
              {!last ? (
                <span
                  aria-hidden="true"
                  className={`absolute left-[13px] top-8 h-[calc(100%-2rem)] w-px lg:left-8 lg:top-[13px] lg:h-px lg:w-[calc(100%-1.25rem)] ${
                    reached ? "bg-accent" : "bg-line"
                  }`}
                />
              ) : null}
              <StepMarker status={agent.status} number={index + 1} />
              <div className="min-w-0 pt-0.5 lg:pt-0">
                <div className="flex items-baseline gap-2">
                  <h3 className="text-[13px] font-medium text-ink">{labels[agent.agent]}</h3>
                  <span className={`font-mono text-[11px] ${stateColor[agent.status]}`}>{stateText[agent.status]}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-ink-soft" title={agent.message}>
                  {agent.message}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function StepMarker({ status, number }: { status: AgentStatus; number: number }): JSX.Element {
  const base = "relative z-10 grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs";
  if (status === "running") {
    return (
      <span className={`${base} border-accent bg-canvas text-accent`}>
        <span aria-hidden="true" className="absolute inset-0 rounded-full ring-2 ring-accent/40 motion-safe:animate-ping" />
        <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden="true" />
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className={`${base} border-accent bg-accent text-on-accent`}>
        <Check className="h-3.5 w-3.5" aria-hidden="true" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className={`${base} border-bad bg-canvas text-bad`}>
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className={`${base} border-dashed border-line-strong bg-canvas text-ink-faint`}>
        <Minus className="h-3.5 w-3.5" aria-hidden="true" />
      </span>
    );
  }
  return <span className={`${base} border-line-strong bg-canvas font-mono text-ink-faint`}>{number}</span>;
}
