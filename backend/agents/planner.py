"""Planner agent for decomposing user tasks into executable steps."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama


class PlannerAgent:
    """Plan an AgentFlow task and choose the agents needed to complete it."""

    def __init__(self, llm: ChatOllama | None = None) -> None:
        """Create a planner that uses a local Ollama llama3.2 model."""

        self.llm = llm or ChatOllama(model="llama3.2:1b")

    def plan(self, task: str) -> dict[str, list[str]]:
        """Return subtasks, required agents, and execution order for a task."""

        prompt = (
            "Analyze the user's task and identify which AgentFlow agents are needed. "
            "Available agents are: file_agent for uploaded CSV, JSON, or TXT files; "
            "code_agent for Python calculations, transformations, charts, or analysis; "
            "reporter for producing a final markdown report. "
            "Decompose the task into 2 to 4 concise subtasks. "
            "Return only valid JSON with this exact shape: "
            '{"subtasks": ["..."], "agents_needed": ["..."], "execution_order": ["..."]}.'
        )

        try:
            response = self.llm.invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=task),
                ]
            )
            content = str(response.content).strip()
            parsed = self._parse_json(content)
            return self._normalize_plan(parsed)
        except Exception:
            return self._fallback_plan(task)

    def __call__(self, task: str) -> dict[str, list[str]]:
        """Plan a task when the agent instance is called directly."""

        return self.plan(task)

    def _parse_json(self, content: str) -> dict[str, Any]:
        """Parse raw LLM content into a dictionary, tolerating fenced JSON."""

        if content.startswith("```"):
            content = content.strip("`").strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("Planner response did not contain a JSON object.")

        parsed = json.loads(content[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("Planner response JSON must be an object.")
        return parsed

    def _normalize_plan(self, parsed: dict[str, Any]) -> dict[str, list[str]]:
        """Validate planner JSON and ensure required report generation exists."""

        subtasks = self._string_list(parsed.get("subtasks"))
        agents_needed = self._string_list(parsed.get("agents_needed"))
        execution_order = self._string_list(parsed.get("execution_order"))

        valid_agents = {"file_agent", "code_agent", "reporter"}
        agents_needed = [agent for agent in agents_needed if agent in valid_agents]
        execution_order = [agent for agent in execution_order if agent in valid_agents]

        if not subtasks:
            subtasks = ["Analyze the task requirements.", "Generate a final report."]

        if "reporter" not in agents_needed:
            agents_needed.append("reporter")
        if "reporter" not in execution_order:
            execution_order.append("reporter")

        if not execution_order:
            execution_order = agents_needed.copy()

        return {
            "subtasks": subtasks[:4],
            "agents_needed": agents_needed,
            "execution_order": execution_order,
        }

    def _string_list(self, value: Any) -> list[str]:
        """Convert a JSON value into a clean list of strings."""

        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _fallback_plan(self, task: str) -> dict[str, list[str]]:
        """Create a deterministic plan if the local LLM is unavailable."""

        lowered = task.lower()
        agents_needed: list[str] = []
        subtasks = ["Understand the user's objective and expected output."]

        if any(keyword in lowered for keyword in ("csv", "json", "txt", "file", "upload")):
            agents_needed.append("file_agent")
            subtasks.append("Read and summarize the uploaded file data.")

        if any(
            keyword in lowered
            for keyword in ("analyze", "calculate", "chart", "plot", "code", "python", "visualize")
        ):
            agents_needed.append("code_agent")
            subtasks.append("Run Python analysis needed to answer the task.")

        agents_needed.append("reporter")
        subtasks.append("Write a clean markdown report with findings and conclusion.")

        return {
            "subtasks": subtasks[:4],
            "agents_needed": agents_needed,
            "execution_order": agents_needed.copy(),
        }
