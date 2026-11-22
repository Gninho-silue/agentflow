"""Reporter fact checking with a scripted fake LLM."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from backend.agents.reporter import ReporterAgent
from backend.tests.test_facts import CORRECT, FACTS

WRONG_SUPERLATIVE = CORRECT + "* Home products have the highest average price among the three categories.\n"
INVENTED_NUMBER = CORRECT + "* Total revenue reached 1,234.50.\n"
CONTRADICTION = (
    "# Summary\nElectronics have the highest average price (94.00).\n"
    "Sports have the highest average price as well.\n"
)


class RecordingLLM:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[list[BaseMessage]] = []

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.prompts.append(messages)
        return AIMessage(content=self.replies.pop(0))


def state(facts: dict[str, Any] | None = FACTS) -> dict[str, Any]:
    return {
        "task": "Analyze the product catalog",
        "subtasks": [],
        "file_data": {"summary": "12 rows", "columns": [], "rows": [], "row_count": 12},
        "code_output": "price table",
        "chart_path": None,
        "error": None,
        "code_attempts": [],
        "computed_facts": facts,
    }


def text(messages: list[BaseMessage]) -> str:
    return "\n".join(str(m.content) for m in messages)


def test_correct_report_is_kept_and_facts_are_in_the_prompt() -> None:
    llm = RecordingLLM(CORRECT)
    report, check = ReporterAgent(llm=llm).write_checked_report(state())  # type: ignore[arg-type]

    assert report == CORRECT.strip()
    assert check == {"passed": True, "attempts": 1, "errors": []}
    prompt = text(llm.prompts[0])
    assert '"max": "Electronics"' in prompt  # the facts JSON
    assert "only" in prompt.lower() and "computed facts" in prompt.lower()


def test_invented_number_is_fixed_by_one_regeneration() -> None:
    llm = RecordingLLM(INVENTED_NUMBER, CORRECT)
    report, check = ReporterAgent(llm=llm).write_checked_report(state())  # type: ignore[arg-type]

    assert report == CORRECT.strip()
    assert check == {"passed": True, "attempts": 2, "errors": []}
    retry = text(llm.prompts[1])
    assert "The number 1,234.50 does not appear in the computed results." in retry
    assert INVENTED_NUMBER.strip() in retry  # the previous draft is shown


def test_wrong_superlative_twice_adds_a_visible_warning() -> None:
    llm = RecordingLLM(WRONG_SUPERLATIVE, WRONG_SUPERLATIVE, "never used")
    report, check = ReporterAgent(llm=llm).write_checked_report(state())  # type: ignore[arg-type]

    assert check["passed"] is False and check["attempts"] == 2
    assert "## ⚠️ Fact check" in report
    assert "'Home' is not the highest for price: the highest is Electronics." in report
    assert report.startswith(WRONG_SUPERLATIVE.rstrip())
    assert llm.replies == ["never used"]  # exactly one regeneration


def test_internal_contradiction_twice_adds_a_warning() -> None:
    llm = RecordingLLM(CONTRADICTION, CONTRADICTION)
    report, check = ReporterAgent(llm=llm).write_checked_report(state())  # type: ignore[arg-type]

    assert check["passed"] is False
    assert "Contradiction on price" in report


def test_without_computed_facts_nothing_is_checked() -> None:
    llm = RecordingLLM("Revenue was 123 456.")
    report, check = ReporterAgent(llm=llm).write_checked_report(state(facts=None))  # type: ignore[arg-type]

    assert report == "Revenue was 123 456."
    assert check == {"passed": True, "attempts": 1, "errors": [], "skipped": "no computed facts"}


def test_write_report_keeps_returning_text() -> None:
    llm = RecordingLLM(CORRECT)
    assert ReporterAgent(llm=llm).write_report(state()) == CORRECT.strip()  # type: ignore[arg-type]
