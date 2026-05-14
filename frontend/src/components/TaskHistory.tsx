import { Trash2 } from "lucide-react";
import type { TaskRecord } from "../types";

interface TaskHistoryProps {
  apiBase: string;
  selectedTaskId: string | null;
  tasks: TaskRecord[];
  onSelect: (task: TaskRecord) => void;
  onTaskDeleted: (taskId: string) => void;
  onAllTasksDeleted: () => void;
}

export function TaskHistory({
  apiBase,
  selectedTaskId,
  tasks,
  onSelect,
  onTaskDeleted,
  onAllTasksDeleted,
}: TaskHistoryProps): JSX.Element {
  const deleteTask = async (taskId: string) => {
    const response = await fetch(`${apiBase}/api/tasks/${taskId}`, { method: "DELETE" });
    if (response.ok) {
      onTaskDeleted(taskId);
    }
  };

  const clearAll = async () => {
    if (!window.confirm("Delete all history?")) {
      return;
    }
    const response = await fetch(`${apiBase}/api/tasks`, { method: "DELETE" });
    if (response.ok) {
      onAllTasksDeleted();
    }
  };

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">Recent</h2>
      </div>

      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
        {tasks.length === 0 ? (
          <p className="rounded-lg px-2 py-3 text-xs text-slate-500">No recent tasks.</p>
        ) : (
          tasks.map((task) => (
            <div
              key={task.task_id}
              className={`group flex items-center gap-2 rounded-lg p-2 transition-all duration-200 hover:bg-white/5 ${
                selectedTaskId === task.task_id ? "bg-white/5" : "bg-transparent"
              }`}
            >
              <button type="button" onClick={() => onSelect(task)} className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[13px] text-slate-200">{task.task}</span>
                <span className="mt-1 inline-flex">
                  <StatusBadge status={task.status} />
                </span>
              </button>

              <button
                type="button"
                onClick={() => void deleteTask(task.task_id)}
                className="rounded-md p-1.5 text-slate-500 opacity-0 transition-all duration-200 hover:bg-red-500/10 hover:text-red-400 group-hover:opacity-100"
                aria-label="Delete task"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          ))
        )}
      </div>

      {tasks.length > 0 ? (
        <button
          type="button"
          onClick={() => void clearAll()}
          className="mt-3 w-fit text-xs font-medium text-red-400 transition-all duration-200 hover:text-red-300"
        >
          Clear all
        </button>
      ) : null}
    </section>
  );
}

function StatusBadge({ status }: { status: string }): JSX.Element {
  if (status === "completed") {
    return <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-400">completed</span>;
  }
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-400">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400" />
        running
      </span>
    );
  }
  if (status === "error") {
    return <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs text-red-400">error</span>;
  }
  return <span className="rounded-full bg-white/5 px-2 py-0.5 text-xs text-slate-400">{status}</span>;
}
