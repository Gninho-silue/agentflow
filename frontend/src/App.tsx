import { useCallback, useEffect, useState } from "react";
import { AgentPipeline } from "./components/AgentPipeline";
import { BackendBanner, BackendStatusPill } from "./components/BackendStatus";
import { ExamplePicker } from "./components/ExamplePicker";
import { ResultViewer } from "./components/ResultViewer";
import { TaskHistory } from "./components/TaskHistory";
import { TaskInput, type TaskPreset } from "./components/TaskInput";
import { useBackendStatus } from "./hooks/useBackendStatus";
import { useWebSocket } from "./hooks/useWebSocket";
import type { TaskRecord } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export default function App(): JSX.Element {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<TaskRecord | null>(null);
  const [history, setHistory] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [preset, setPreset] = useState<TaskPreset | null>(null);
  const { agents, task, connected } = useWebSocket(taskId);
  const backend = useBackendStatus(API_BASE);

  const loadHistory = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/tasks`);
      if (response.ok) {
        setHistory((await response.json()) as TaskRecord[]);
      }
    } catch {
      // Reachability is reported by useBackendStatus.
    }
  }, []);

  useEffect(() => {
    if (backend.status === "online") void loadHistory();
  }, [backend.status, loadHistory]);

  useEffect(() => {
    if (task) {
      setSelectedTask(task);
      void loadHistory();
    }
  }, [loadHistory, task]);

  const runTask = async (taskText: string, file: File | null) => {
    setLoading(true);
    setApiError(null);
    setSelectedTask(null);
    try {
      let filePath: string | null = null;
      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        const uploadResponse = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
        if (!uploadResponse.ok) {
          throw new Error(await errorDetail(uploadResponse, "The file could not be uploaded."));
        }
        filePath = ((await uploadResponse.json()) as { file_path: string }).file_path;
      }

      const createResponse = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task: taskText, file_path: filePath }),
      });
      if (!createResponse.ok) {
        throw new Error(await errorDetail(createResponse, "The task could not be created."));
      }
      const created = (await createResponse.json()) as { task_id: string };
      setTaskId(created.task_id);

      const executeResponse = await fetch(`${API_BASE}/api/tasks/${created.task_id}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: filePath }),
      });
      if (!executeResponse.ok) {
        throw new Error(await errorDetail(executeResponse, "The task could not be started."));
      }
      await loadHistory();
    } catch (error) {
      setApiError(
        error instanceof TypeError
          ? `The server at ${API_BASE} did not answer. Check that the backend is running, then try again.`
          : error instanceof Error
            ? error.message
            : "Something went wrong while starting the task.",
      );
      backend.retry();
    } finally {
      setLoading(false);
    }
  };

  const selectTask = (record: TaskRecord) => {
    setSelectedTask(record);
    setApiError(null);
  };

  const handleTaskDeleted = (deletedTaskId: string) => {
    setHistory((current) => current.filter((item) => item.task_id !== deletedTaskId));
    if (selectedTask?.task_id === deletedTaskId) setSelectedTask(null);
    if (taskId === deletedTaskId) setTaskId(null);
  };

  const handleAllTasksDeleted = () => {
    setHistory([]);
    setSelectedTask(null);
    setTaskId(null);
  };

  const running = loading || connected;

  return (
    <div className="min-h-screen bg-canvas font-sans text-ink">
      <a href="#workspace" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm">
        Skip to results
      </a>
      <header className="border-b border-line">
        <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h1 className="text-[17px] font-semibold tracking-tight text-ink">AgentFlow</h1>
            <p className="truncate text-xs text-ink-soft">Five AI agents plan, read, code and report on your data.</p>
          </div>
          <BackendStatusPill status={backend.status} />
        </div>
        <BackendBanner status={backend.status} apiBase={API_BASE} onRetry={backend.retry} />
      </header>

      <div className="flex flex-col lg:min-h-[calc(100vh-4rem)] lg:flex-row">
        <aside className="flex w-full shrink-0 flex-col gap-6 border-b border-line p-4 sm:p-6 lg:w-[360px] lg:border-b-0 lg:border-r">
          <ExamplePicker onPick={(taskText, file) => setPreset({ task: taskText, file, nonce: Date.now() })} />
          <TaskInput onRun={runTask} loading={loading} error={apiError} preset={preset} />
          <div className="hidden min-h-0 flex-1 lg:block">
            <TaskHistory
              apiBase={API_BASE}
              selectedTaskId={selectedTask?.task_id ?? null}
              tasks={history}
              onSelect={selectTask}
              onTaskDeleted={handleTaskDeleted}
              onAllTasksDeleted={handleAllTasksDeleted}
            />
          </div>
        </aside>

        <main id="workspace" className="min-w-0 flex-1 p-4 sm:p-6">
          <div className="mx-auto flex max-w-6xl flex-col gap-6">
            <AgentPipeline agents={agents} connected={connected} />
            {selectedTask ? (
              <ResultViewer task={selectedTask} apiBase={API_BASE} />
            ) : (
              <ResultPlaceholder running={running} />
            )}
            <div className="lg:hidden">
              <TaskHistory
                apiBase={API_BASE}
                selectedTaskId={selectedTask?.task_id ?? null}
                tasks={history}
                onSelect={selectTask}
                onTaskDeleted={handleTaskDeleted}
                onAllTasksDeleted={handleAllTasksDeleted}
              />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function ResultPlaceholder({ running }: { running: boolean }): JSX.Element {
  return (
    <section aria-live="polite" className="rounded-xl border border-dashed border-line p-8 text-center">
      {running ? (
        <>
          <h2 className="text-[15px] font-semibold text-ink">The agents are working on it</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-soft">
            Progress shows in the pipeline above. A local model on CPU can take a few minutes; the report appears here when
            the Supervisor finishes.
          </p>
        </>
      ) : (
        <>
          <h2 className="text-[15px] font-semibold text-ink">No result yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-soft">
            Pick an example or describe a task, add a CSV, JSON or TXT file if you have one, then run AgentFlow.
          </p>
        </>
      )}
    </section>
  );
}

async function errorDetail(response: Response, fallback: string): Promise<string> {
  if (response.status === 429) return "Too many tasks in a minute. Wait a moment, then try again.";
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Non-JSON error body.
  }
  return `${fallback} (HTTP ${response.status})`;
}
