"""Functional tests for the subprocess sandbox and the pluggable Sandbox interface."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from backend.agents.code_agent import CodeAgent
from backend.sandbox import SandboxResult, SubprocessSandbox
from backend.tests.helpers import fake_llm
from backend.tools.code_executor import CodeExecutor, SandboxExecutionError

SALES = {"columns": ["category", "total"], "rows": [{"category": "A", "total": 10}, {"category": "B", "total": 5}]}


@pytest.fixture(scope="module")
def sandbox() -> SubprocessSandbox:
    return SubprocessSandbox()


def test_runs_code_with_dataframe_and_returns_stdout(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run("print(df['total'].sum())", SALES)
    assert result.ok
    assert result.stdout == "15"
    assert result.images == []


def test_error_returns_message_and_user_only_traceback(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run("x = 1\nprint(df['missing'])", SALES)
    assert not result.ok
    assert result.error_type == "KeyError"
    assert result.traceback is not None
    assert 'File "<generated>", line 2' in result.traceback
    assert "_child.py" not in result.traceback  # sandbox internals are hidden


def test_syntax_error_is_reported(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run("print(", SALES)
    assert not result.ok
    assert result.error_type == "SyntaxError"


def test_open_figure_is_returned_as_png(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run("df.plot(kind='bar', x='category', y='total')", SALES)
    assert result.ok
    assert len(result.images) == 1
    assert result.images[0].startswith(b"\x89PNG")


def test_explicit_savefig_is_not_duplicated(sandbox: SubprocessSandbox) -> None:
    code = "import matplotlib.pyplot as plt\nplt.plot([1, 2])\nplt.savefig('chart.png')"
    result = sandbox.run(code, SALES)
    assert result.ok
    assert len(result.images) == 1


def test_input_file_is_copied_into_workdir(sandbox: SubprocessSandbox, tmp_path: Path) -> None:
    upload = tmp_path / "sales.csv"
    upload.write_text("category,total\nA,3\nA,4\n", encoding="utf-8")

    result = sandbox.run("print(pd.read_csv('sales.csv')['total'].sum())", input_files=[upload])
    assert result.ok, result.error
    assert result.stdout == "7"
    assert upload.read_text(encoding="utf-8") == "category,total\nA,3\nA,4\n"


def test_can_write_scratch_files_in_workdir(sandbox: SubprocessSandbox) -> None:
    code = "df.to_csv('copy.csv', index=False)\nprint(pd.read_csv('copy.csv').shape)"
    result = sandbox.run(code, SALES)
    assert result.ok, result.error
    assert result.stdout == "(2, 2)"


def test_working_directory_is_deleted_afterwards(sandbox: SubprocessSandbox) -> None:
    before = set(Path(tempfile.gettempdir()).glob("agentflow-run-*"))
    sandbox.run("df.to_csv('leftover.csv')", SALES)
    after = set(Path(tempfile.gettempdir()).glob("agentflow-run-*"))
    assert after <= before


def test_huge_output_is_truncated(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run("for i in range(100000):\n    print('line', i)", SALES)
    assert result.ok
    assert len(result.stdout) <= 200_000


def test_disallowed_imports_are_refused(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run("import os", SALES)
    assert not result.ok
    assert "not allowed" in (result.error or "")


def test_executor_raises_with_result_attached() -> None:
    with pytest.raises(SandboxExecutionError) as info:
        CodeExecutor().execute("print(1 / 0)")
    assert str(info.value) == "division by zero"
    assert info.value.result.error_type == "ZeroDivisionError"


# --- Pluggable interface ----------------------------------------------------


class RecordingSandbox:
    """A stand-in for a hosted sandbox (E2B, ...): agents only see the interface."""

    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        code: str,
        file_data: dict[str, Any] | None = None,
        input_files: list[Path] | None = None,
    ) -> SandboxResult:
        self.calls.append({"code": code, "file_data": file_data, "input_files": input_files})
        return self.result


def test_code_agent_uses_injected_sandbox(tmp_path: Path) -> None:
    upload = tmp_path / "sales.csv"
    upload.write_text("a\n1\n", encoding="utf-8")
    fake = RecordingSandbox(SandboxResult(ok=True, stdout="42"))
    agent = CodeAgent(llm=fake_llm("print(42)"), executor=CodeExecutor(sandbox=fake))

    result = agent.run("Compute the answer", SALES, file_path=str(upload))

    assert result["output"] == "42"
    assert result["success"] is True
    assert len(result["attempts"]) == 1
    assert fake.calls[0]["input_files"] == [upload]


def test_code_agent_reports_sandbox_failure() -> None:
    failure = SandboxResult(ok=False, error="boom", error_type="ValueError", traceback="Traceback...")
    agent = CodeAgent(llm=fake_llm("print(1)"), executor=CodeExecutor(sandbox=RecordingSandbox(failure)))

    result = agent.run("Compute", SALES)

    assert result["success"] is False
    assert result["output"] == "boom"
    assert result["traceback"] == "Traceback..."


def test_code_agent_saves_chart_image(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    image = b"\x89PNG fake"
    agent = CodeAgent(
        llm=fake_llm("plt.plot([1])"),
        executor=CodeExecutor(sandbox=RecordingSandbox(SandboxResult(ok=True, images=[image]))),
    )

    result = agent.run("Plot totals", SALES)

    chart = result["output"].split("[chart_path]:")[1].strip()
    assert chart.startswith("uploads/chart_")
    assert (tmp_path / chart).read_bytes() == image


def test_charts_use_the_dark_interface_palette(sandbox: SubprocessSandbox) -> None:
    import io

    from PIL import Image

    result = sandbox.run("df.plot(kind='bar', x='category', y='total')", SALES)
    image = Image.open(io.BytesIO(result.images[0])).convert("RGB")
    # Background of the report panel (#151b23), not matplotlib's default white.
    assert image.getpixel((2, 2)) == (0x15, 0x1B, 0x23)
