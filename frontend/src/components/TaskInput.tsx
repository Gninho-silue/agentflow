import { ChangeEvent, DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import { Loader2, Play, UploadCloud, X } from "lucide-react";

/** Values pushed from outside (one-click examples). A new nonce re-applies them. */
export interface TaskPreset {
  task: string;
  file: File | null;
  nonce: number;
}

interface TaskInputProps {
  onRun: (task: string, file: File | null) => Promise<void>;
  loading: boolean;
  error: string | null;
  preset?: TaskPreset | null;
}

const MAX_TASK_LENGTH = 2000;
const MIN_TASK_LENGTH = 3;
const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB
const ALLOWED_EXTENSIONS = new Set([".csv", ".json", ".txt"]);

function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function validateFile(f: File): string | null {
  const ext = fileExtension(f.name);
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    return `"${ext || "(none)"}" is not allowed. Upload a .csv, .json, or .txt file.`;
  }
  if (f.size > MAX_FILE_BYTES) {
    return "File exceeds the 10 MB size limit.";
  }
  return null;
}

export function TaskInput({ onRun, loading, error, preset = null }: TaskInputProps): JSX.Element {
  const [task, setTask] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!preset) return;
    setTask(preset.task);
    setFile(preset.file);
    setValidationError(null);
  }, [preset]);

  const charCount = task.length;
  const overLimit = charCount > MAX_TASK_LENGTH;
  const canSubmit = !loading && task.trim().length >= MIN_TASK_LENGTH && !overLimit;
  const displayError = validationError ?? error;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setValidationError(null);

    if (!task.trim()) {
      setValidationError("Task text is required.");
      return;
    }
    if (task.trim().length < MIN_TASK_LENGTH) {
      setValidationError(`Task must be at least ${MIN_TASK_LENGTH} characters.`);
      return;
    }
    if (overLimit) {
      setValidationError(`Task must not exceed ${MAX_TASK_LENGTH} characters.`);
      return;
    }
    if (file) {
      const fileErr = validateFile(file);
      if (fileErr) {
        setValidationError(fileErr);
        return;
      }
    }

    await onRun(task.trim(), file);
  };

  const handleFile = (f: File | null) => {
    if (!f) {
      setFile(null);
      return;
    }
    const err = validateFile(f);
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    setFile(f);
  };

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    handleFile(event.target.files?.[0] ?? null);
  };

  const dropFile = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    handleFile(event.dataTransfer.files?.[0] ?? null);
  };

  const removeFile = () => {
    setFile(null);
    setValidationError(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="relative">
        <textarea
          aria-label="Task description"
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="Analyze a CSV file and generate a report..."
          className="min-h-40 w-full resize-none rounded-xl border-0 bg-surface p-4 pb-7 text-[14px] leading-6 text-ink outline-none placeholder:text-ink-faint ring-1 ring-transparent transition-all duration-200 focus:ring-accent/60"
        />
        <span
          className={`pointer-events-none absolute bottom-2.5 right-3 text-[11px] tabular-nums ${
            overLimit ? "text-bad" : "text-ink-faint"
          }`}
        >
          {charCount} / {MAX_TASK_LENGTH}
        </span>
      </div>

      {displayError ? (
        <div className="rounded-xl border border-bad/30 bg-bad/10 p-3 text-xs leading-5 text-bad">
          {displayError}
        </div>
      ) : null}

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={dropFile}
        className={`flex min-h-28 cursor-pointer flex-col focus-within:border-accent focus-within:outline focus-within:outline-2 focus-within:outline-accent items-center justify-center rounded-xl border border-dashed p-4 text-center transition-all duration-200 ${
          dragging ? "border-accent/60 bg-raised" : "border-line hover:border-accent/60"
        }`}
      >
        <input ref={inputRef} className="sr-only" type="file" accept=".csv,.json,.txt" aria-label="Upload CSV, JSON, or TXT file" onChange={selectFile} />
        <UploadCloud className="mb-2 h-5 w-5 text-ink-soft" aria-hidden="true" />
        {file ? (
          <div className="flex max-w-full items-center gap-2">
            <span className="truncate text-[13px] font-medium text-ink">{file.name}</span>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                removeFile();
              }}
              className="rounded-md p-1 text-ink-faint transition-all duration-200 hover:bg-raised hover:text-ink"
              aria-label="Remove file"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        ) : (
          <>
            <span className="text-[13px] text-ink-soft">Upload CSV, JSON, or TXT</span>
            <span className="mt-1 text-xs text-ink-faint">Drop file here or click to browse</span>
          </>
        )}
      </div>

      <button
        type="submit"
        disabled={!canSubmit}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-[13px] font-medium text-on-accent transition-all duration-200 hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-raised disabled:text-ink-faint"
      >
        {loading ? <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
        {loading ? "Running..." : "Run AgentFlow"}
      </button>
    </form>
  );
}
