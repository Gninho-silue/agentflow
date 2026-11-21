import { useEffect, useMemo, useState } from "react";
import type { AgentName, AgentProgress, AgentStatus, CodeAttempt, TaskRecord } from "../types";
import { wsUrl } from "../api";

const initialAgents: AgentProgress[] = [
  { agent: "planner", status: "idle", message: "Waiting for task." },
  { agent: "file_agent", status: "idle", message: "No file processed yet." },
  { agent: "code_agent", status: "idle", message: "No code executed yet." },
  { agent: "reporter", status: "idle", message: "Report not generated yet." },
  { agent: "supervisor", status: "idle", message: "Workflow not started." },
];


interface AgentUpdateEvent {
  type: "agent_update";
  agent: string;
  message: string;
  status: string;
}

interface TaskEvent {
  type: "task";
  task: TaskRecord;
}

interface CodeAttemptEvent {
  type: "code_attempt";
  attempt: number;
  code: string;
  error: string | null;
  traceback: string | null;
}

interface CompleteEvent {
  type: "complete";
  status: "completed" | "error";
}

export function useWebSocket(taskId: string | null): {
  agents: AgentProgress[];
  task: TaskRecord | null;
  attempts: CodeAttempt[];
  connected: boolean;
} {
  const [agents, setAgents] = useState<AgentProgress[]>(initialAgents);
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [attempts, setAttempts] = useState<CodeAttempt[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setAgents(initialAgents);
    setTask(null);
    setAttempts([]);
    if (!taskId) {
      return;
    }

    const socket = new WebSocket(wsUrl(taskId));
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (event: MessageEvent<string>) => {
      const payload = JSON.parse(event.data) as AgentUpdateEvent | TaskEvent | CompleteEvent | CodeAttemptEvent;
      if (payload.type === "code_attempt") {
        const attempt = toAttempt(payload);
        setAttempts((current) => [...current.filter((a) => a.attempt !== attempt.attempt), attempt]);
        setAgents((current) => current.map((agent) => (agent.agent === "code_agent" ? attemptProgress(agent, attempt) : agent)));
        return;
      }
      if (payload.type === "task") {
        setTask(payload.task);
        const finalAttempts = payload.task.result?.code_attempts;
        if (finalAttempts) {
          setAttempts(finalAttempts.map(toAttempt));
        }
        if (payload.task.status === "completed") {
          setAgents((current) => completeAgents(current, "completed"));
          setConnected(false);
        }
        if (payload.task.status === "error") {
          setAgents((current) => completeAgents(current, "error"));
          setConnected(false);
        }
        return;
      }
      if (payload.type === "complete") {
        setAgents((current) => completeAgents(current, payload.status));
        setConnected(false);
        return;
      }
      if (payload.type === "agent_update") {
        setAgents((current) => updateAgent(current, payload));
      }
    };

    return () => socket.close();
  }, [taskId]);

  return useMemo(() => ({ agents, task, attempts, connected }), [agents, task, attempts, connected]);
}

function toAttempt(source: CodeAttempt): CodeAttempt {
  return { attempt: source.attempt, code: source.code, error: source.error, traceback: source.traceback };
}

function attemptProgress(agent: AgentProgress, attempt: CodeAttempt): AgentProgress {
  if (attempt.error) {
    return { ...agent, status: "running", message: `Attempt ${attempt.attempt} failed: ${attempt.error}. Retrying...` };
  }
  return { ...agent, message: `Attempt ${attempt.attempt} succeeded.` };
}

function completeAgents(current: AgentProgress[], status: "completed" | "error"): AgentProgress[] {
  if (status === "completed") {
    // Agents that never reported progress were not part of the plan.
    return current.map((agent) =>
      agent.status === "idle"
        ? { ...agent, status: "skipped", message: "Not needed for this task." }
        : { ...agent, status: "done" },
    );
  }

  return current.map((agent) => ({
    ...agent,
    status: agent.status === "running" ? "error" : agent.status,
  }));
}

function updateAgent(current: AgentProgress[], payload: AgentUpdateEvent): AgentProgress[] {
  const agent = normalizeAgent(payload.agent);
  const status = normalizeStatus(payload.status);
  const activeIndex = current.findIndex((item) => item.agent === agent);
  return current.map((item) => {
    if (item.agent === agent) {
      return { ...item, status, message: payload.message };
    }
    if (status === "running" && activeIndex > -1 && current.findIndex((candidate) => candidate.agent === item.agent) < activeIndex) {
      return item.status === "running" ? { ...item, status: "done" } : item;
    }
    return item;
  });
}

function normalizeAgent(agent: string): AgentName {
  if (agent === "file_agent" || agent === "code_agent" || agent === "reporter" || agent === "supervisor") {
    return agent;
  }
  return "planner";
}

function normalizeStatus(status: string): AgentStatus {
  if (status === "error") {
    return "error";
  }
  if (status === "completed") {
    return "done";
  }
  if (status === "running") {
    return "running";
  }
  return "idle";
}
