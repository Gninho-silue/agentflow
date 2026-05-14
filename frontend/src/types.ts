export type AgentName = "planner" | "file_agent" | "code_agent" | "reporter" | "supervisor";

export type AgentStatus = "idle" | "running" | "done" | "error";

export interface AgentProgress {
  agent: AgentName;
  status: AgentStatus;
  message: string;
}

export interface TaskResult {
  task: string;
  subtasks: string[];
  current_agent: string;
  file_data: Record<string, unknown> | null;
  code_output: string | null;
  chart_path: string | null;
  report: string | null;
  status: string;
  error: string | null;
  messages: string[];
}

export interface TaskRecord {
  task_id: string;
  task: string;
  file_path: string | null;
  status: string;
  result: TaskResult | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  execution_time: number | null;
  agents_used: string[];
}
