import { Brain, CheckCircle2, Circle, FileOutput, FileText, Loader2, ShieldCheck, Terminal, XCircle } from "lucide-react";
import type { AgentName, AgentProgress, AgentStatus } from "../types";

interface AgentPipelineProps {
  agents: AgentProgress[];
  connected: boolean;
}

const icons: Record<AgentName, typeof Brain> = {
  planner: Brain,
  file_agent: FileText,
  code_agent: Terminal,
  reporter: FileOutput,
  supervisor: ShieldCheck,
};

const labels: Record<AgentName, string> = {
  planner: "Planner",
  file_agent: "FileAgent",
  code_agent: "CodeAgent",
  reporter: "Reporter",
  supervisor: "Supervisor",
};

export function AgentPipeline({ agents, connected }: AgentPipelineProps): JSX.Element {
  return (
    <section className="rounded-xl border border-borderline bg-panel/70 p-5 backdrop-blur-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold uppercase tracking-widest text-slate-400">Pipeline</h2>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "animate-pulse bg-indigo-500" : "bg-slate-600"}`} />
          {connected ? "Live" : "Idle"}
        </div>
      </div>

      <div className="flex items-stretch gap-3 overflow-x-auto">
        {agents.map((agent, index) => {
          const Icon = icons[agent.agent];
          return (
            <div key={agent.agent} className="flex min-w-[150px] flex-1 items-center gap-3">
              <article className="min-h-32 min-w-0 flex-1 rounded-xl border border-borderline bg-panel p-4 transition-all duration-200">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <Icon className="h-5 w-5 text-slate-300" aria-hidden="true" />
                  <StatusIcon status={agent.status} />
                </div>
                <h3 className="truncate text-[13px] font-medium text-slate-100">{labels[agent.agent]}</h3>
                <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-slate-400">{agent.message}</p>
              </article>
              {index < agents.length - 1 ? <div className="hidden h-px w-5 shrink-0 border-t border-dashed border-borderline xl:block" /> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function StatusIcon({ status }: { status: AgentStatus }): JSX.Element {
  if (status === "running") {
    return <Loader2 className="h-4 w-4 animate-spin text-indigo-400" aria-label="running" />;
  }
  if (status === "done") {
    return <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-label="done" />;
  }
  if (status === "error") {
    return <XCircle className="h-4 w-4 text-red-400" aria-label="error" />;
  }
  return <Circle className="h-4 w-4 text-slate-600" aria-label="idle" />;
}
