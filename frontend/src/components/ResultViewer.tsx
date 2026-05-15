import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { Download } from "lucide-react";
import type { Components } from "react-markdown";
import type { TaskRecord } from "../types";

interface ResultViewerProps {
  task: TaskRecord | null;
}

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

export function ResultViewer({ task }: ResultViewerProps): JSX.Element | null {
  if (!task || (!task.result && task.status !== "error")) {
    return null;
  }

  const report = sanitizeReport(task?.result?.report ?? "");
  const metadata = [
    task.execution_time ? `${task.execution_time}s` : null,
    task.agents_used?.length ? task.agents_used.join(" → ") : null,
  ]
    .filter(Boolean)
    .join(" · ");

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

  return (
    <section className="rounded-xl border border-borderline bg-panel/70 p-5 backdrop-blur-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 className="text-base font-semibold text-slate-100">Result</h2>
            {metadata ? <p className="text-xs text-slate-400">{metadata}</p> : null}
          </div>
        </div>
        <button
          type="button"
          onClick={downloadReport}
          disabled={!report}
          className="flex items-center gap-2 rounded-lg border border-slate-700 bg-transparent px-3 py-2 text-xs font-medium text-slate-300 transition-all duration-200 hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          Download
        </button>
      </div>

      {task.status === "error" ? (
        <div className="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-300">{task.error}</div>
      ) : null}

      {report ? (
        <div className="rounded-xl border border-borderline bg-panel p-6">
          <ReactMarkdown rehypePlugins={[rehypeRaw]} remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {report}
          </ReactMarkdown>
        </div>
      ) : null}
    </section>
  );
}

const markdownComponents: Components = {
  h1({ children }) {
    return <h1 className="mb-4 mt-1 text-2xl font-semibold text-slate-100">{children}</h1>;
  },
  h2({ children }) {
    return <h2 className="mb-3 mt-6 text-xl font-semibold text-slate-100">{children}</h2>;
  },
  h3({ children }) {
    return <h3 className="mb-2 mt-5 text-base font-semibold text-slate-100">{children}</h3>;
  },
  p({ children }) {
    return <p className="mb-4 text-sm leading-7 text-slate-300">{children}</p>;
  },
  ul({ children }) {
    return <ul className="mb-4 list-disc space-y-2 pl-4 text-sm text-slate-300">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="mb-4 list-decimal space-y-2 pl-4 text-sm text-slate-300">{children}</ol>;
  },
  li({ children }) {
    return <li className="leading-6">{children}</li>;
  },
  table({ children }) {
    return (
      <div className="mb-5 overflow-x-auto rounded-lg border border-borderline">
        <table className="w-full border-collapse text-left text-sm text-slate-300">{children}</table>
      </div>
    );
  },
  thead({ children }) {
    return <thead className="bg-white/5 text-slate-100">{children}</thead>;
  },
  th({ children }) {
    return <th className="border-b border-borderline px-3 py-2 font-medium">{children}</th>;
  },
  td({ children }) {
    return <td className="border-b border-borderline px-3 py-2 last:border-b-0">{children}</td>;
  },
  pre({ children }) {
    return <>{children}</>;
  },
  code({ inline, children, ...props }: any) {
    if (inline) {
      return (
        <code className="rounded bg-slate-950 px-1.5 py-0.5 font-mono text-[13px] text-emerald-400" {...props}>
          {children}
        </code>
      );
    }
    return (
      <pre className="mb-5 overflow-x-auto rounded-lg bg-[#020617] p-4">
        <code className="font-mono text-[13px] leading-6 text-emerald-400" {...props}>
          {children}
        </code>
      </pre>
    );
  },
  // Only render img tags that point to our own uploads — block all other src values
  img({ src, alt }) {
    const safeSrc = typeof src === "string" && src.startsWith("/uploads/") ? src : undefined;
    if (!safeSrc) return null;
    return <img src={safeSrc} alt={alt ?? "Chart"} className="max-w-full rounded-lg" />;
  },
};
