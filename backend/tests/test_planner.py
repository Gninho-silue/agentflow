"""Characterization tests for PlannerAgent: JSON parsing and plan normalization."""

from __future__ import annotations

import pytest

from backend.agents.planner import PlannerAgent
from backend.tests.helpers import fake_llm


def plan_with(response: str, task: str = "Do something") -> dict[str, list[str]]:
    return PlannerAgent(llm=fake_llm(response)).plan(task)


# --- JSON parsing -----------------------------------------------------------


def test_parses_plain_json() -> None:
    plan = plan_with(
        '{"subtasks": ["a", "b"], "agents_needed": ["code_agent", "reporter"], '
        '"execution_order": ["code_agent", "reporter"]}'
    )
    assert plan == {
        "subtasks": ["a", "b"],
        "agents_needed": ["code_agent", "reporter"],
        "execution_order": ["code_agent", "reporter"],
    }


def test_parses_json_code_fence() -> None:
    response = (
        "```json\n"
        '{"subtasks": ["a"], "agents_needed": ["file_agent"], "execution_order": ["file_agent"]}\n'
        "```"
    )
    plan = plan_with(response)
    assert plan["subtasks"] == ["a"]
    assert plan["agents_needed"] == ["file_agent", "reporter"]


def test_parses_json_surrounded_by_text() -> None:
    response = (
        "Sure! Here is the plan:\n"
        '{"subtasks": ["x"], "agents_needed": ["code_agent"], "execution_order": ["code_agent"]}\n'
        "Hope this helps."
    )
    plan = plan_with(response)
    assert plan["subtasks"] == ["x"]
    assert plan["execution_order"] == ["code_agent", "reporter"]


@pytest.mark.parametrize(
    "response",
    [
        "I cannot produce JSON today.",
        '{"subtasks": ["broken", }',
        '["a", "list", "not", "an", "object"]',
    ],
)
def test_invalid_json_falls_back_to_keyword_plan(response: str) -> None:
    plan = plan_with(response, task="Analyze this CSV file and plot a chart")
    assert plan["agents_needed"] == ["file_agent", "code_agent", "reporter"]
    assert plan["execution_order"] == plan["agents_needed"]
    assert plan["subtasks"][0] == "Understand the user's objective and expected output."


def test_fallback_without_keywords_only_uses_reporter() -> None:
    plan = plan_with("not json", task="Say hello")
    assert plan["agents_needed"] == ["reporter"]
    assert len(plan["subtasks"]) == 2


def test_llm_exception_falls_back() -> None:
    class BrokenLLM:
        def invoke(self, _messages: object) -> object:
            raise ConnectionError("Ollama is down")

    plan = PlannerAgent(llm=BrokenLLM()).plan("calculate the total")  # type: ignore[arg-type]
    assert plan["agents_needed"] == ["code_agent", "reporter"]


# --- Normalization ----------------------------------------------------------


def test_unknown_agents_are_filtered() -> None:
    plan = plan_with(
        '{"subtasks": ["a"], "agents_needed": ["web_agent", "code_agent", "hacker"], '
        '"execution_order": ["web_agent", "code_agent"]}'
    )
    assert plan["agents_needed"] == ["code_agent", "reporter"]
    assert plan["execution_order"] == ["code_agent", "reporter"]


def test_reporter_is_always_added() -> None:
    plan = plan_with('{"subtasks": ["a"], "agents_needed": [], "execution_order": []}')
    assert plan["agents_needed"] == ["reporter"]
    assert plan["execution_order"] == ["reporter"]


def test_reporter_not_duplicated() -> None:
    plan = plan_with(
        '{"subtasks": ["a"], "agents_needed": ["reporter"], "execution_order": ["reporter"]}'
    )
    assert plan["agents_needed"] == ["reporter"]
    assert plan["execution_order"] == ["reporter"]


def test_subtasks_capped_at_four() -> None:
    plan = plan_with(
        '{"subtasks": ["1", "2", "3", "4", "5", "6"], "agents_needed": [], "execution_order": []}'
    )
    assert plan["subtasks"] == ["1", "2", "3", "4"]


def test_missing_subtasks_get_defaults_and_non_strings_dropped() -> None:
    plan = plan_with(
        '{"subtasks": [1, null, "  "], "agents_needed": "code_agent", "execution_order": null}'
    )
    assert plan["subtasks"] == ["Analyze the task requirements.", "Generate a final report."]
    assert plan["agents_needed"] == ["reporter"]
