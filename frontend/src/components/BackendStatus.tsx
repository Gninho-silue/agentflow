import { Loader2, RefreshCw } from "lucide-react";
import type { BackendStatus } from "../hooks/useBackendStatus";

const pillText: Record<BackendStatus, string> = {
  checking: "Connecting",
  waking: "Server waking up",
  online: "Server ready",
  offline: "Server unreachable",
};

const dotColor: Record<BackendStatus, string> = {
  checking: "bg-ink-faint",
  waking: "bg-accent motion-safe:animate-pulse",
  online: "bg-ok",
  offline: "bg-bad",
};

export function BackendStatusPill({ status }: { status: BackendStatus }): JSX.Element {
  return (
    <p className="flex shrink-0 items-center gap-2 text-xs text-ink-soft" role="status">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dotColor[status]}`} />
      {pillText[status]}
    </p>
  );
}

interface BannerProps {
  status: BackendStatus;
  apiBase: string;
  onRetry: () => void;
}

export function BackendBanner({ status, apiBase, onRetry }: BannerProps): JSX.Element | null {
  if (status === "waking") {
    return (
      <div className="flex items-start gap-3 border-t border-line bg-accent/10 px-4 py-3 text-sm text-ink sm:px-6">
        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 text-accent motion-safe:animate-spin" aria-hidden="true" />
        <p>
          The server is waking up. The free hosting plan puts it to sleep when nobody uses it, so the first request can
          take up to a minute. You can prepare your task meanwhile.
        </p>
      </div>
    );
  }
  if (status === "offline") {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 border-t border-line bg-bad/10 px-4 py-3 text-sm text-ink sm:px-6">
        <p className="min-w-0 flex-1">
          The server at <span className="font-mono text-[13px]">{apiBase}</span> is not answering. If you run AgentFlow
          locally, start the backend with <span className="font-mono text-[13px]">uvicorn backend.main:app</span>.
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="flex items-center gap-2 rounded-lg border border-line-strong px-3 py-1.5 text-xs font-medium text-ink hover:bg-raised"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Try again
        </button>
      </div>
    );
  }
  return null;
}
