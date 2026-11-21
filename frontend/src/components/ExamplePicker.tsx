import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { EXAMPLES, loadExampleFile, type Example } from "../examples";

interface ExamplePickerProps {
  onPick: (task: string, file: File) => void;
}

/** One-click examples: a visitor rarely has a dataset at hand. */
export function ExamplePicker({ onPick }: ExamplePickerProps): JSX.Element {
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pick = async (example: Example) => {
    setLoadingId(example.id);
    setError(null);
    try {
      onPick(example.task, await loadExampleFile(example));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load the example.");
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
        <Sparkles className="h-3 w-3" aria-hidden="true" />
        Try an example
      </div>
      <div className="flex flex-col gap-1.5">
        {EXAMPLES.map((example) => (
          <button
            key={example.id}
            type="button"
            onClick={() => void pick(example)}
            disabled={loadingId !== null}
            className="flex items-center justify-between gap-2 rounded-lg border border-borderline px-3 py-2 text-left transition-all duration-200 hover:border-indigo-500/40 disabled:opacity-60"
          >
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-slate-200">{example.label}</span>
              <span className="block truncate text-[11px] text-slate-500">{example.description}</span>
            </span>
            {loadingId === example.id ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-slate-400" aria-hidden="true" /> : null}
          </button>
        ))}
      </div>
      {error ? (
        <p role="alert" className="text-xs text-red-300">
          {error}
        </p>
      ) : null}
    </div>
  );
}
