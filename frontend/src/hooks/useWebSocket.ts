import { useEffect, useMemo, useState } from "react";
import type { AgentName, AgentProgress, AgentStatus, TaskRecord } from "../types";

const initialAgents: AgentProgress[] = [
  { agent: "planner", status: "idle", message: "Waiting for task." },
  { agent: "file_agent", status: "idle", message: "No file processed yet." },
  { agent: "code_agent", status: "idle", message: "No code executed yet." },
  { agent: "reporter", status: "idle", message: "Report not generated yet." },
  { agent: "supervisor", status: "idle", message: "Workflow not started." },
];

const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";

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

interface CompleteEvent {
  type: "complete";
  status: "completed" | "error";
}

export function useWebSocket(taskId: string | null): {
  agents: AgentProgress[];
  task: TaskRecord | null;
  connected: boolean;
} {
  const [agents, setAgents] = useState<AgentProgress[]>(initialAgents);
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setAgents(initialAgents);
    setTask(null);
    if (!taskId) {
      return;
    }

    const socket = new WebSocket(`${WS_BASE}/ws/${taskId}`);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (event: MessageEvent<string>) => {
      const payload = JSON.parse(event.data) as AgentUpdateEvent | TaskEvent | CompleteEvent;
      if (payload.type === "task") {
        setTask(payload.task);
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

  return useMemo(() => ({ agents, task, connected }), [agents, task, connected]);
}

function completeAgents(current: AgentProgress[], status: "completed" | "error"): AgentProgress[] {
  if (status === "completed") {
    return current.map((agent) => ({
      ...agent,
      status: "done",
      message: agent.status === "idle" ? "Completed." : agent.message,
    }));
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
