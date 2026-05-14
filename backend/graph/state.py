"""Shared LangGraph state for AgentFlow workflows."""

from __future__ import annotations

from typing import Literal, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """State passed between AgentFlow's specialized agents."""

    task: str
    subtasks: list[str]
    current_agent: str
    file_data: dict | None
    code_output: str | None
    chart_path: str | None
    report: str | None
    messages: list[BaseMessage]
    status: Literal["running", "completed", "error"]
    error: str | None
    file_path: str | None
    agents_needed: list[str]
    execution_order: list[str]
    completed_agents: list[str]
