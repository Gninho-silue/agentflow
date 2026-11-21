"""Workflow tests: the real LangGraph graph driven by a scripted fake LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from backend.agents.file_agent import FileAgent
from backend.agents.planner import PlannerAgent
from backend.agents.reporter import ReporterAgent
from backend.graph.workflow import create_workflow
from backend.tests.helpers import PLAN_WITH_FILE, PLAN_WITHOUT_FILE, REPORT, fake_llm


def initial_state(task: str, file_path: str | None = None) -> dict[str, Any]:
    return {
        "task": task,
        "subtasks": [],
        "current_agent": "planner",
        "file_data": None,
        "code_output": None,
        "chart_path": None,
        "report": None,
        "messages": [HumanMessage(content=task)],
        "status": "running",
        "error": None,
        "file_path": file_path,
        "agents_needed": [],
        "execution_order": [],
        "completed_agents": [],
        "code_attempts": [],
    }


def run(graph: Any, state: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Stream the graph and return (visited nodes, final state)."""

    visited: list[str] = []
    final = state
    for chunk in graph.stream(state):
        node, final = next(iter(chunk.items()))
        visited.append(node)
    return visited, final


@pytest.fixture(autouse=True)
def _isolate_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)


def test_routes_through_file_agent_when_file_is_planned(sample_csv: Path) -> None:
    graph = create_workflow(
        llm=fake_llm(PLAN_WITH_FILE, "print(df['total'].sum())", REPORT)
    )
    visited, final = run(graph, initial_state("Compute total sales from the CSV", str(sample_csv)))

    assert visited == ["planner", "file_agent", "code_agent", "reporter", "supervisor"]
    assert final["status"] == "completed"
    assert final["error"] is None
    assert final["file_data"]["columns"] == ["category", "total"]
    assert final["file_data"]["row_count"] == 3
    assert final["code_output"] == "22"
    assert final["report"] == REPORT
    assert final["completed_agents"] == ["file_agent", "code_agent", "reporter"]


def test_skips_file_agent_without_file() -> None:
    graph = create_workflow(llm=fake_llm(PLAN_WITHOUT_FILE, "print(6 * 7)", REPORT))
    visited, final = run(graph, initial_state("What is six times seven?"))

    assert "file_agent" not in visited
    assert visited == ["planner", "code_agent", "reporter", "supervisor"]
    assert final["status"] == "completed"
    assert final["file_data"] is None
    assert final["code_output"] == "42"
    assert final["completed_agents"] == ["code_agent", "reporter"]
    assert final["code_attempts"] == [
        {"attempt": 1, "code": "print(6 * 7)", "error": None, "traceback": None, "output": "42"}
    ]


def test_file_agent_reports_missing_upload_without_crashing() -> None:
    """Planner asked for the FileAgent but no file was uploaded."""

    graph = create_workflow(llm=fake_llm(PLAN_WITH_FILE, "print('ok')", REPORT))
    visited, final = run(graph, initial_state("Read the CSV"))

    assert visited[:2] == ["planner", "file_agent"]
    assert final["file_data"]["summary"] == "No file was uploaded for this task."
    assert final["status"] == "completed"


def test_code_fixed_on_second_attempt() -> None:
    graph = create_workflow(
        llm=fake_llm(PLAN_WITHOUT_FILE, "print(1 / 0)", "print(6 * 7)", REPORT)
    )
    _, final = run(graph, initial_state("Compute something"))

    assert final["status"] == "completed"
    assert final["code_output"] == "42"
    assert final["error"] is None
    attempts = final["code_attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert attempts[0]["error"] == "division by zero"
    assert "ZeroDivisionError" in attempts[0]["traceback"]
    assert attempts[1]["error"] is None
    assert "Code execution failed" not in final["report"]


def test_three_failed_attempts_reach_the_reporter() -> None:
    """The pipeline still produces a report, and the report says the code failed."""

    graph = create_workflow(
        llm=fake_llm(PLAN_WITHOUT_FILE, "print(1 / 0)", "print(2 / 0)", "print(3 / 0)", REPORT)
    )
    visited, final = run(graph, initial_state("Compute something"))

    assert visited == ["planner", "code_agent", "reporter", "supervisor"]
    assert final["status"] == "completed"
    assert final["code_output"] == "division by zero"
    assert final["error"] == "division by zero"
    assert len(final["code_attempts"]) == 3
    assert final["report"].startswith(REPORT)
    assert "## Code execution failed" in final["report"]
    assert "3 attempts" in final["report"]
    assert "division by zero" in final["report"]


@pytest.mark.parametrize(
    ("target", "method", "expected_visited"),
    [
        (PlannerAgent, "plan", ["planner"]),
        (FileAgent, "read_file", ["planner", "file_agent"]),
        (ReporterAgent, "write_report", ["planner", "file_agent", "code_agent", "reporter"]),
    ],
)
def test_agent_exception_ends_workflow_in_clean_error_state(
    monkeypatch: pytest.MonkeyPatch,
    sample_csv: Path,
    target: type,
    method: str,
    expected_visited: list[str],
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(target, method, explode)
    graph = create_workflow(llm=fake_llm(PLAN_WITH_FILE, "print('ok')", REPORT))
    visited, final = run(graph, initial_state("Compute total from CSV", str(sample_csv)))

    assert visited == expected_visited
    assert final["status"] == "error"
    assert final["error"] == "agent exploded"
    assert "failed: agent exploded" in str(final["messages"][-1].content)


def test_chart_request_produces_chart_file(sample_csv: Path) -> None:
    chart_code = (
        "import matplotlib.pyplot as plt\n"
        "plt.figure()\n"
        "df.groupby('category')['total'].sum().plot(kind='bar')\n"
        "plt.savefig('chart.png')\n"
        "print('done')"
    )
    graph = create_workflow(llm=fake_llm(PLAN_WITH_FILE, chart_code, REPORT))
    _, final = run(graph, initial_state("Plot total by category", str(sample_csv)))

    assert final["status"] == "completed"
    assert "[chart_path]: uploads/chart_" in final["code_output"]
    chart_rel = final["code_output"].split("[chart_path]:")[1].strip()
    assert Path(chart_rel).is_file()
    assert f'<img src="/{chart_rel}"' in final["report"]
