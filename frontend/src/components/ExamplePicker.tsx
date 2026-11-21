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
      <h2 className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
        <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        Try an example
      </h2>
      <div className="flex flex-col gap-1.5">
        {EXAMPLES.map((example) => (
          <button
            key={example.id}
            type="button"
            onClick={() => void pick(example)}
            disabled={loadingId !== null}
            className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-left transition-all duration-200 hover:border-accent/60 disabled:opacity-60"
          >
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-ink">{example.label}</span>
              <span className="block truncate text-[11px] text-ink-faint">{example.description}</span>
            </span>
            {loadingId === example.id ? <Loader2 className="h-3.5 w-3.5 shrink-0 motion-safe:animate-spin text-ink-soft" aria-hidden="true" /> : null}
          </button>
        ))}
      </div>
      {error ? (
        <p role="alert" className="text-xs text-bad">
          {error}
        </p>
      ) : null}
    </div>
  );
}
