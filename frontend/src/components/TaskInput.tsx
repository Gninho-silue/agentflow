import { ChangeEvent, DragEvent, FormEvent, useRef, useState } from "react";
import { Loader2, Play, UploadCloud, X } from "lucide-react";

interface TaskInputProps {
  onRun: (task: string, file: File | null) => Promise<void>;
  loading: boolean;
  error: string | null;
}

export function TaskInput({ onRun, loading, error }: TaskInputProps): JSX.Element {
  const [task, setTask] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!task.trim()) {
      return;
    }
    await onRun(task.trim(), file);
  };

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const dropFile = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    setFile(event.dataTransfer.files?.[0] ?? null);
  };

  const removeFile = () => {
    setFile(null);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <textarea
        value={task}
        onChange={(event) => setTask(event.target.value)}
        placeholder="Analyze a CSV file and generate a report..."
        className="min-h-40 w-full resize-none rounded-xl border-0 bg-panel p-4 text-[13px] leading-6 text-slate-100 outline-none placeholder:text-slate-500 ring-1 ring-transparent transition-all duration-200 focus:ring-indigo-500/40"
      />

      {error ? (
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-xs leading-5 text-red-300">
          {error}
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
        className={`flex min-h-28 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed p-4 text-center transition-all duration-200 ${
          dragging ? "border-indigo-500/40 bg-white/[0.03]" : "border-borderline hover:border-indigo-500/40"
        }`}
      >
        <input ref={inputRef} className="hidden" type="file" accept=".csv,.json,.txt" onChange={selectFile} />
        <UploadCloud className="mb-2 h-5 w-5 text-slate-400" aria-hidden="true" />
        {file ? (
          <div className="flex max-w-full items-center gap-2">
            <span className="truncate text-[13px] font-medium text-slate-200">{file.name}</span>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                removeFile();
              }}
              className="rounded-md p-1 text-slate-500 transition-all duration-200 hover:bg-white/5 hover:text-slate-200"
              aria-label="Remove file"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        ) : (
          <>
            <span className="text-[13px] text-slate-300">Upload CSV, JSON, or TXT</span>
            <span className="mt-1 text-xs text-slate-500">Drop file here or click to browse</span>
          </>
        )}
      </div>

      <button
        type="submit"
        disabled={loading || !task.trim()}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-[13px] font-medium text-white transition-all duration-200 hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
        {loading ? "Running..." : "Run AgentFlow"}
      </button>
    </form>
  );
}
