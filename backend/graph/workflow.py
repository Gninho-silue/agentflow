"""LangGraph workflow wiring for AgentFlow."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from backend.agents.code_agent import CodeAgent
from backend.agents.file_agent import FileAgent
from backend.agents.planner import PlannerAgent
from backend.agents.reporter import ReporterAgent
from backend.graph.state import AgentState


LLM_MODEL = "llama3.2:1b"


def create_workflow() -> Any:
    """Build and compile the AgentFlow StateGraph."""

    llm = ChatOllama(model=LLM_MODEL)
    planner = PlannerAgent(llm=llm)
    file_agent = FileAgent()
    code_agent = CodeAgent(llm=llm)
    reporter = ReporterAgent(llm=llm)

    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner_node(planner))
    graph.add_node("file_agent", _file_node(file_agent))
    graph.add_node("code_agent", _code_node(code_agent))
    graph.add_node("reporter", _reporter_node(reporter))
    graph.add_node("supervisor", _supervisor_node)

    graph.set_entry_point("planner")
    graph.add_conditional_edges(
        "planner",
        _route_from_planner,
        {
            "file_agent": "file_agent",
            "code_agent": "code_agent",
            "end": END,
        },
    )
    graph.add_edge("file_agent", "code_agent")
    graph.add_edge("code_agent", "reporter")
    graph.add_edge("reporter", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "planner": "planner",
            "end": END,
        },
    )

    return graph.compile()


def _planner_node(planner: PlannerAgent) -> Any:
    """Create the planner node closure."""

    def node(state: AgentState) -> AgentState:
        try:
            plan = planner.plan(state["task"])
            messages = state.get("messages", [])
            messages.append(AIMessage(content=f"Planner created subtasks: {plan['subtasks']}"))

            return {
                **state,
                "subtasks": plan["subtasks"],
                "agents_needed": plan["agents_needed"],
                "execution_order": plan["execution_order"],
                "completed_agents": [],
                "current_agent": _route_from_plan(plan["agents_needed"]),
                "messages": messages,
                "status": "running",
                "error": None,
            }
        except Exception as exc:
            return _error_state(state, "planner", exc)

    return node


def _file_node(file_agent: FileAgent) -> Any:
    """Create the file-agent node closure."""

    def node(state: AgentState) -> AgentState:
        try:
            file_path = str(state.get("file_path", "")).strip()
            file_data = (
                file_agent.read_file(file_path)
                if file_path
                else {
                    "columns": [],
                    "rows": [],
                    "summary": "No file was uploaded for this task.",
                    "row_count": 0,
                }
            )
            messages = state.get("messages", [])
            messages.append(AIMessage(content=f"FileAgent completed: {file_data.get('summary')}"))
            return {
                **state,
                "file_data": file_data,
                "completed_agents": _mark_completed(state, "file_agent"),
                "current_agent": "code_agent",
                "messages": messages,
                "status": "running",
                "error": None,
            }
        except Exception as exc:
            return _error_state(state, "file_agent", exc)

    return node


def _code_node(code_agent: CodeAgent) -> Any:
    """Create the code-agent node closure."""

    def node(state: AgentState) -> AgentState:
        try:
            result = code_agent.run(task=state["task"], file_data=state.get("file_data"))
            messages = state.get("messages", [])
            messages.append(AIMessage(content=f"CodeAgent completed. Success: {result['success']}"))
            return {
                **state,
                "code_output": str(result["output"]),
                "completed_agents": _mark_completed(state, "code_agent"),
                "current_agent": "reporter",
                "messages": messages,
                "status": "running",
                "error": None if result["success"] else str(result["output"]),
            }
        except Exception as exc:
            return _error_state(state, "code_agent", exc)

    return node


def _reporter_node(reporter: ReporterAgent) -> Any:
    """Create the reporter node closure."""

    def node(state: AgentState) -> AgentState:
        try:
            report = reporter.write_report(state)
            messages = state.get("messages", [])
            messages.append(AIMessage(content="ReporterAgent generated the final report."))
            return {
                **state,
                "report": report,
                "completed_agents": _mark_completed(state, "reporter"),
                "current_agent": "supervisor",
                "messages": messages,
                "status": "running",
                "error": None,
            }
        except Exception as exc:
            return _error_state(state, "reporter", exc)

    return node


def _supervisor_node(state: AgentState) -> AgentState:
    """Mark the workflow completed when a report exists, otherwise retry planning."""

    try:
        messages = state.get("messages", [])
        status = "completed" if state.get("report") else "running"
        messages.append(AIMessage(content=f"Supervisor checked workflow progress. Status: {status}."))

        return {
            **state,
            "current_agent": "supervisor" if status == "completed" else "planner",
            "messages": messages,
            "status": status,
            "error": state.get("error"),
        }
    except Exception as exc:
        return _error_state(state, "supervisor", exc)


def _route_from_planner(state: AgentState) -> str:
    """Route from planner to FileAgent when needed, otherwise CodeAgent."""

    if state.get("status") == "error":
        return "end"
    if "file_agent" in state.get("agents_needed", []):
        return "file_agent"
    return "code_agent"


def _route_from_supervisor(state: AgentState) -> str:
    """End completed workflows; otherwise retry from planner."""

    if state.get("status") == "completed":
        return "end"
    return "planner"


def _route_from_plan(agents_needed: list[str]) -> str:
    """Return the first node after planning under AgentFlow's fixed routing rules."""

    return "file_agent" if "file_agent" in agents_needed else "code_agent"


def _mark_completed(state: AgentState, agent_name: str) -> list[str]:
    """Return completed agents with agent_name appended once."""

    completed = list(state.get("completed_agents", []))
    if agent_name not in completed:
        completed.append(agent_name)
    return completed


def _error_state(state: AgentState, agent_name: str, exc: Exception) -> AgentState:
    """Update state after an agent failure."""

    messages = state.get("messages", [])
    messages.append(AIMessage(content=f"{agent_name} failed: {exc}"))
    return {
        **state,
        "current_agent": agent_name,
        "messages": messages,
        "status": "error",
        "error": str(exc),
    }


workflow = create_workflow()
