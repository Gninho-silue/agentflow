import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { Check, CircleAlert, CircleCheck, Copy, Download } from "lucide-react";
import type { Components } from "react-markdown";
import type { CodeAttempt, TaskRecord } from "../types";
import { CodeBlock } from "./CodeBlock";

interface ResultViewerProps {
  task: TaskRecord | null;
  /** Backend origin: charts are served by the API under /uploads/. */
  apiBase: string;
}

const AGENT_LABELS: Record<string, string> = {
  planner: "Planner",
  file_agent: "FileAgent",
  code_agent: "CodeAgent",
  reporter: "Reporter",
  supervisor: "Supervisor",
};

/**
 * Strip script/iframe tags and inline event handlers from LLM-generated report
 * text before passing it to the markdown renderer.
 */
function sanitizeReport(raw: string): string {
  return raw
    .replace(/<script\b[\s\S]*?<\/script>/gi, "")
    .replace(/<iframe\b[\s\S]*?<\/iframe>/gi, "")
    .replace(/\bon[a-z]{1,20}\s*=\s*(?:"[^"]*"|'[^']*'|\S+)/gi, "");
}

function formatSeconds(seconds: number): string {
  return seconds < 0.1 ? "<0.1s" : `${seconds.toFixed(1)}s`;
}

export function ResultViewer({ task, apiBase }: ResultViewerProps): JSX.Element | null {
  const [copied, setCopied] = useState(false);
  const components = useMemo(() => markdownComponents(apiBase), [apiBase]);

  if (!task || (!task.result && task.status !== "error")) {
    return null;
  }

  const report = sanitizeReport(task.result?.report ?? "");
  const attempts: CodeAttempt[] = task.result?.code_attempts ?? [];
  const finalCode = attempts.length ? attempts[attempts.length - 1].code : null;
  const showAttempts = attempts.length > 1 || attempts.some((attempt) => attempt.error);
  const durations = Object.entries(task.result?.agent_durations ?? {});
  // The per-agent durations below already list the agents that ran.
  const metadata = task.execution_time ? `Ran in ${task.execution_time.toFixed(1)}s` : null;

  const downloadReport = () => {
    if (!report) {
      return;
    }
    const blob = new Blob([report], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `agentflow-report-${task.task_id}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const copyReport = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const buttonClass =
    "flex items-center gap-2 rounded-lg border border-line-strong bg-transparent px-3 py-2 text-xs font-medium text-ink-soft transition-all duration-200 hover:border-ink-faint disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <section className="rounded-xl border border-line bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 className="text-base font-semibold text-ink">Result</h2>
            {metadata ? <p className="font-mono text-xs text-ink-soft">{metadata}</p> : null}
          </div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => void copyReport()} disabled={!report} className={buttonClass}>
            {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
            {copied ? "Copied" : "Copy"}
          </button>
          <button type="button" onClick={downloadReport} disabled={!report} className={buttonClass}>
            <Download className="h-4 w-4" aria-hidden="true" />
            Download
          </button>
        </div>
      </div>

      {durations.length ? (
        <ul aria-label="Duration per agent" className="mb-4 flex flex-wrap gap-2">
          {durations.map(([agent, seconds]) => (
            <li key={agent} className="flex items-center gap-1.5 rounded-md bg-raised px-2 py-1 text-[11px] text-ink-soft">
              <span className="text-ink-soft">{AGENT_LABELS[agent] ?? agent}</span>
              <span className="font-mono tabular-nums">{formatSeconds(seconds)}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {task.status === "error" ? (
        <div className="mb-4 rounded-xl border border-bad/30 bg-bad/10 p-4 text-sm text-bad">{task.error}</div>
      ) : null}

      {report ? (
        <div className="rounded-xl border border-line bg-surface p-6">
          <ReactMarkdown rehypePlugins={[rehypeRaw]} remarkPlugins={[remarkGfm]} components={components}>
            {report}
          </ReactMarkdown>
        </div>
      ) : null}

      {showAttempts ? (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold text-ink">Self-correction</h3>
          <ol aria-label="Code attempts" className="flex flex-col gap-2">
            {attempts.map((attempt) => (
              <li key={attempt.attempt} className="rounded-lg border border-line p-3">
                <div className="flex items-center gap-2 text-[13px]">
                  {attempt.error ? (
                    <CircleAlert className="h-4 w-4 text-bad" aria-hidden="true" />
                  ) : (
                    <CircleCheck className="h-4 w-4 text-ok" aria-hidden="true" />
                  )}
                  <span className="font-medium text-ink">Attempt {attempt.attempt}</span>
                  <span className={attempt.error ? "text-bad" : "text-ok"}>
                    {attempt.error ? `failed: ${attempt.error}` : "succeeded"}
                  </span>
                </div>
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-ink-soft">Code{attempt.traceback ? " and traceback" : ""}</summary>
                  <div className="mt-2 flex flex-col gap-2">
                    <CodeBlock code={attempt.code} />
                    {attempt.traceback ? <CodeBlock code={attempt.traceback} language="text" /> : null}
                  </div>
                </details>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {finalCode ? (
        <details className="mt-4 rounded-lg border border-line p-3">
          <summary className="cursor-pointer text-sm font-semibold text-ink">Generated code</summary>
          <div className="mt-3">
            <CodeBlock code={finalCode} />
          </div>
        </details>
      ) : null}
    </section>
  );
}

function markdownComponents(apiBase: string): Components {
  const base = apiBase.replace(/\/+$/, "");
  return {
    h1({ children }) {
      return <h1 className="mb-4 mt-1 text-2xl font-semibold text-ink">{children}</h1>;
    },
    h2({ children }) {
      return <h2 className="mb-3 mt-6 text-xl font-semibold text-ink">{children}</h2>;
    },
    h3({ children }) {
      return <h3 className="mb-2 mt-5 text-base font-semibold text-ink">{children}</h3>;
    },
    p({ children }) {
      return <p className="mb-4 text-sm leading-7 text-ink-soft">{children}</p>;
    },
    ul({ children }) {
      return <ul className="mb-4 list-disc space-y-2 pl-4 text-sm text-ink-soft">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="mb-4 list-decimal space-y-2 pl-4 text-sm text-ink-soft">{children}</ol>;
    },
    li({ children }) {
      return <li className="leading-6">{children}</li>;
    },
    table({ children }) {
      return (
        <div className="mb-5 overflow-x-auto rounded-lg border border-line">
          <table className="w-full border-collapse text-left text-sm text-ink-soft">{children}</table>
        </div>
      );
    },
    thead({ children }) {
      return <thead className="bg-raised text-ink">{children}</thead>;
    },
    th({ children }) {
      return <th className="border-b border-line px-3 py-2 font-medium">{children}</th>;
    },
    td({ children }) {
      return <td className="border-b border-line px-3 py-2 last:border-b-0">{children}</td>;
    },
    // Fenced blocks: the <pre> carries the block style and resets the inline <code> style.
    pre({ children }) {
      return (
        <pre className="mb-5 overflow-x-auto rounded-lg bg-canvas p-4 font-mono text-[13px] leading-6 text-ok [&_code]:bg-transparent [&_code]:p-0">
          {children}
        </pre>
      );
    },
    code({ children, className }) {
      return (
        <code className={`rounded bg-canvas px-1.5 py-0.5 font-mono text-[13px] text-ok ${className ?? ""}`}>
          {children}
        </code>
      );
    },
    // Only our own chart uploads are rendered, loaded from the backend origin.
    img({ src, alt }) {
      if (typeof src !== "string" || !src.startsWith("/uploads/")) return null;
      return <img src={`${base}${src}`} alt={alt ?? "Chart"} className="max-w-full rounded-lg" />;
    },
  };
}
