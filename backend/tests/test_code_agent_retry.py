"""Self-correction loop of the CodeAgent (fake LLM + scripted sandbox, no subprocess)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from backend.agents.code_agent import MAX_ATTEMPTS, CodeAgent
from backend.sandbox import SandboxResult
from backend.tools.code_executor import CodeExecutor

DATA = {"columns": ["a"], "rows": [{"a": 1}], "summary": "1 row"}


class RecordingLLM:
    """Returns scripted replies and keeps every prompt it received."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[list[BaseMessage]] = []

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.prompts.append(messages)
        return AIMessage(content=self.replies.pop(0))


class ScriptedSandbox:
    """Returns the scripted results in order and records the code it ran."""

    def __init__(self, *results: SandboxResult) -> None:
        self.results = list(results)
        self.codes: list[str] = []

    def run(
        self,
        code: str,
        file_data: dict[str, Any] | None = None,
        input_files: list[Path] | None = None,
    ) -> SandboxResult:
        self.codes.append(code)
        return self.results.pop(0)


def failure(message: str, error_type: str = "KeyError") -> SandboxResult:
    return SandboxResult(
        ok=False,
        error=message,
        error_type=error_type,
        traceback=f'File "<generated>", line 1, in <module>\n{error_type}: {message}',
    )


def make_agent(llm: RecordingLLM, sandbox: ScriptedSandbox) -> CodeAgent:
    return CodeAgent(llm=llm, executor=CodeExecutor(sandbox=sandbox))  # type: ignore[arg-type]


def prompt_text(messages: list[BaseMessage]) -> str:
    return "\n".join(str(message.content) for message in messages)


def test_max_attempts_is_three() -> None:
    assert MAX_ATTEMPTS == 3


def test_success_on_first_attempt() -> None:
    llm = RecordingLLM("print(1)")
    sandbox = ScriptedSandbox(SandboxResult(ok=True, stdout="1"))

    result = make_agent(llm, sandbox).run("Compute", DATA)

    assert result["success"] is True
    assert result["output"] == "1"
    assert result["attempts"] == [
        {"attempt": 1, "code": "print(1)", "error": None, "traceback": None, "output": "1"}
    ]
    assert len(llm.prompts) == 1


def test_failure_then_success_on_second_attempt() -> None:
    llm = RecordingLLM("print(df['b'])", "print(df['a'].sum())")
    sandbox = ScriptedSandbox(failure("'b'"), SandboxResult(ok=True, stdout="1"))

    result = make_agent(llm, sandbox).run("Sum column a", DATA)

    assert result["success"] is True
    assert result["output"] == "1"
    assert result["code"] == "print(df['a'].sum())"
    assert [a["attempt"] for a in result["attempts"]] == [1, 2]
    assert result["attempts"][0]["error"] == "'b'"
    assert result["attempts"][0]["code"] == "print(df['b'])"
    assert result["attempts"][1]["error"] is None

    correction = prompt_text(llm.prompts[1])
    assert "print(df['b'])" in correction  # the failing code
    assert "KeyError: 'b'" in correction  # its traceback
    assert "Sum column a" in correction  # the original task
    assert sandbox.codes[1] == "print(df['a'].sum())"


def test_three_failures_stop_and_report_last_error() -> None:
    llm = RecordingLLM("bad1", "bad2", "bad3", "never used")
    sandbox = ScriptedSandbox(failure("e1"), failure("e2"), failure("e3"))

    result = make_agent(llm, sandbox).run("Compute", DATA)

    assert result["success"] is False
    assert result["output"] == "e3"
    assert result["error"] == "e3"
    assert len(result["attempts"]) == 3
    assert [a["error"] for a in result["attempts"]] == ["e1", "e2", "e3"]
    assert len(llm.prompts) == 3  # 1 generation + 2 corrections
    assert llm.replies == ["never used"]


def test_unsafe_code_counts_as_failed_attempt_and_is_corrected() -> None:
    llm = RecordingLLM("print(open('x').read())", "print(2)")
    sandbox = ScriptedSandbox(SandboxResult(ok=True, stdout="2"))

    result = make_agent(llm, sandbox).run("Compute", DATA)

    assert result["success"] is True
    assert result["attempts"][0]["error"] == "Blocked: unsafe code detected."
    assert sandbox.codes == ["print(2)"]  # unsafe code never reached the sandbox
    assert "unsafe" in prompt_text(llm.prompts[1]).lower()


def test_correction_strips_markdown_fences() -> None:
    llm = RecordingLLM("print(x)", "```python\nprint(3)\n```")
    sandbox = ScriptedSandbox(failure("name 'x' is not defined", "NameError"), SandboxResult(ok=True, stdout="3"))

    result = make_agent(llm, sandbox).run("Compute", DATA)

    assert sandbox.codes[1] == "print(3)"
    assert result["output"] == "3"


def test_reporter_prompt_forbids_calling_half_a_majority() -> None:
    from backend.agents.reporter import ReporterAgent

    prompt = ReporterAgent(llm=RecordingLLM())._system_prompt()  # type: ignore[arg-type]
    assert "strictly more than 50%" in prompt
    assert "exact numbers" in prompt
