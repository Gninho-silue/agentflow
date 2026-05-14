import { useCallback, useEffect, useState } from "react";
import { AgentPipeline } from "./components/AgentPipeline";
import { ResultViewer } from "./components/ResultViewer";
import { TaskHistory } from "./components/TaskHistory";
import { TaskInput } from "./components/TaskInput";
import { useWebSocket } from "./hooks/useWebSocket";
import type { TaskRecord } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export default function App(): JSX.Element {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<TaskRecord | null>(null);
  const [history, setHistory] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const { agents, task, connected } = useWebSocket(taskId);

  const loadHistory = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/tasks`);
      if (!response.ok) {
        setApiError(`Backend returned ${response.status} while loading task history.`);
        return;
      }
      setHistory((await response.json()) as TaskRecord[]);
      setApiError(null);
    } catch {
      setApiError("Backend is not reachable at http://localhost:8000. Start the FastAPI server, then retry.");
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (task) {
      setSelectedTask(task);
      void loadHistory();
    }
  }, [loadHistory, task]);

  const runTask = async (taskText: string, file: File | null) => {
    setLoading(true);
    setApiError(null);
    try {
      let filePath: string | null = null;
      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        const uploadResponse = await fetch(`${API_BASE}/api/upload`, {
          method: "POST",
          body: formData,
        });
        if (!uploadResponse.ok) {
          throw new Error(`Upload failed with status ${uploadResponse.status}.`);
        }
        const upload = (await uploadResponse.json()) as { file_path: string };
        filePath = upload.file_path;
      }

      const createResponse = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task: taskText, file_path: filePath }),
      });
      if (!createResponse.ok) {
        throw new Error(`Task creation failed with status ${createResponse.status}.`);
      }
      const created = (await createResponse.json()) as { task_id: string };
      setTaskId(created.task_id);

      const executeResponse = await fetch(`${API_BASE}/api/tasks/${created.task_id}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: filePath }),
      });
      if (!executeResponse.ok) {
        throw new Error(`Task execution failed with status ${executeResponse.status}.`);
      }
      await loadHistory();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not contact the backend.";
      setApiError(`${message} Make sure the backend is running on http://localhost:8000.`);
    } finally {
      setLoading(false);
    }
  };

  const handleTaskDeleted = (deletedTaskId: string) => {
    setHistory((current) => current.filter((item) => item.task_id !== deletedTaskId));
    if (selectedTask?.task_id === deletedTaskId) {
      setSelectedTask(null);
    }
    if (taskId === deletedTaskId) {
      setTaskId(null);
    }
  };

  const handleAllTasksDeleted = () => {
    setHistory([]);
    setSelectedTask(null);
    setTaskId(null);
  };

  return (
    <div className="min-h-screen bg-navy font-sans text-slate-200">
      <header className="flex h-14 items-center justify-between border-b border-borderline px-6">
        <div className="text-sm font-semibold tracking-tight text-slate-100">AgentFlow</div>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "animate-pulse bg-indigo-500" : "bg-slate-600"}`} />
          {connected ? "Workflow live" : apiError ? "Backend offline" : "Ready"}
        </div>
      </header>

      <div className="flex min-h-[calc(100vh-3.5rem)]">
        <aside className="flex w-80 shrink-0 flex-col border-r border-borderline bg-navy/95 p-5">
          <div className="mb-5">
            <div className="text-[15px] font-semibold text-slate-100">🤖 AgentFlow</div>
            <p className="mt-1 text-xs text-slate-400">Multi-agent automation</p>
          </div>
          <div className="mb-5 h-px bg-borderline" />

          <TaskInput onRun={runTask} loading={loading} error={apiError} />

          <div className="mt-6 min-h-0 flex-1">
            <TaskHistory
              apiBase={API_BASE}
              selectedTaskId={selectedTask?.task_id ?? null}
              tasks={history}
              onSelect={setSelectedTask}
              onTaskDeleted={handleTaskDeleted}
              onAllTasksDeleted={handleAllTasksDeleted}
            />
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto p-6">
          <div className="mx-auto flex max-w-7xl flex-col gap-6">
            <AgentPipeline agents={agents} connected={connected} />
            <ResultViewer task={selectedTask} />
          </div>
        </main>
      </div>
    </div>
  );
}
