"""Code agent for generating and safely executing Python analysis code."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from backend.llm import get_llm

from backend.sandbox import SandboxResult
from backend.tools.code_executor import CodeExecutor


# Cheap pre-filter that rejects obviously malicious code before spawning a
# sandbox. It is NOT the security boundary: see backend/sandbox.
_BLOCKED_PATTERNS: tuple[str, ...] = (
    "subprocess",
    "os.system",
    "os.popen",
    "open(",
    "eval(",
    "exec(",
    "__import__",
    "__builtins__",
    "importlib",
    "shutil",
    "socket",
)

_CHART_DIR = Path("uploads")
_UNSAFE_MESSAGE = "Blocked: unsafe code detected."

MAX_ATTEMPTS = 3


class CodeAgent:
    """Generate Python code with the LLM and run it in an isolated sandbox."""

    def __init__(self, llm: BaseChatModel | None = None, executor: CodeExecutor | None = None) -> None:
        """Create a code agent; the model comes from ``backend.llm.get_llm`` unless injected."""

        self.llm = llm or get_llm()
        self.executor = executor or CodeExecutor()

    def run(
        self,
        task: str,
        file_data: dict[str, Any] | None = None,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Generate code, run it in the sandbox and self-correct on failure.

        When the code fails (exception, or blocked by the safety pre-filter),
        the failing code and its traceback are sent back to the LLM for a fix,
        up to ``MAX_ATTEMPTS`` runs in total. Every attempt is returned in
        ``attempts`` (``attempt``, ``code``, ``error``, ``traceback``, ``output``).

        ``file_path`` (the uploaded file) is copied into the sandbox's working
        directory; the server copy is never exposed.
        """

        attempts: list[dict[str, Any]] = []
        try:
            needs_chart = self._needs_chart(task)
            code = self._initial_code(task, file_data, needs_chart)
            input_files = [Path(file_path)] if file_path and Path(file_path).is_file() else None

            for number in range(1, MAX_ATTEMPTS + 1):
                if self._is_safe_code(code):
                    outcome = self.executor.run(code, file_data, input_files=input_files)
                else:
                    print("[CodeAgent] Blocked: generated code contains unsafe patterns.")
                    outcome = SandboxResult(ok=False, error=_UNSAFE_MESSAGE, error_type="UnsafeCode")

                chart_path = self._save_chart(outcome.images) if (outcome.ok or needs_chart) else None
                success = outcome.ok or bool(needs_chart and chart_path)
                attempts.append(
                    {
                        "attempt": number,
                        "code": code,
                        "error": None if success else outcome.error,
                        "traceback": None if success else outcome.traceback,
                        "output": outcome.stdout,
                    }
                )

                if success:
                    output = (
                        outcome.stdout
                        if outcome.ok and (outcome.stdout or not chart_path)
                        else "Chart generated successfully."
                    )
                    if chart_path:
                        output = f"{output}\n\n[chart_path]: {chart_path}".strip()
                    return {
                        "code": code,
                        "output": output,
                        "success": True,
                        "error": None,
                        "traceback": None,
                        "attempts": attempts,
                    }

                print(f"[CodeAgent] Attempt {number}/{MAX_ATTEMPTS} failed: {outcome.error}")
                if number < MAX_ATTEMPTS:
                    code = self.fix_code(task, file_data, code, outcome)

            last = attempts[-1]
            return {
                "code": last["code"],
                "output": last["error"] or "Execution failed.",
                "success": False,
                "error": last["error"] or "Execution failed.",
                "traceback": last["traceback"],
                "attempts": attempts,
            }
        except Exception as exc:
            print(f"[CodeAgent] Error: {exc}")
            return {
                "code": attempts[-1]["code"] if attempts else "",
                "output": str(exc),
                "success": False,
                "error": str(exc),
                "traceback": None,
                "attempts": attempts,
            }

    def fix_code(
        self,
        task: str,
        file_data: dict[str, Any] | None,
        code: str,
        outcome: SandboxResult,
    ) -> str:
        """Send the failing code and its traceback back to the LLM for a fix."""

        columns = (file_data or {}).get("columns", [])
        error = outcome.traceback or f"{outcome.error_type or 'Error'}: {outcome.error}"
        if outcome.error_type == "UnsafeCode":
            error = (
                f"{outcome.error} The code was rejected before running because it uses a "
                "forbidden pattern (open(, eval(, exec(, __import__, subprocess, os.system, "
                "socket, shutil, importlib, __builtins__)."
            )

        system = f"""
You are a Python data analyst. The code below was written for this task but it failed.
Task: {task}

The data is available as a pandas DataFrame called 'df' with these columns:
{columns}

Fix the code so that it runs and completes the task.
Rules:
- Use only: pandas (pd), matplotlib (plt), the df variable
- Do NOT import csv, os, or open any files
- Do NOT use plt.show() - use plt.savefig() instead
- Print key results using print()

Write ONLY the corrected Python code, no explanation, no markdown backticks.
"""
        response = self.llm.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=f"Code that failed:\n{code}\n\nError:\n{error}"),
            ]
        )
        return self._strip_code_fence(str(response.content).strip())

    def _initial_code(self, task: str, file_data: dict[str, Any] | None, needs_chart: bool) -> str:
        """First version of the code; insists on matplotlib when a chart is requested."""

        code = self.generate_code(task=task, file_data=file_data)
        if needs_chart and self._is_safe_code(code) and not self._contains_chart_code(code):
            code = self.generate_code(task=task, file_data=file_data, force_chart=True)
            if self._is_safe_code(code) and not self._contains_chart_code(code):
                code = self._fallback_chart_code(file_data)
        return code

    def generate_code(self, task: str, file_data: dict[str, Any] | None = None, force_chart: bool = False) -> str:
        """Ask the LLM for Python code that solves the analysis task."""

        file_summary = (file_data or {}).get("summary", "")
        columns = (file_data or {}).get("columns", [])
        rows = (file_data or {}).get("rows", [])
        needs_chart = force_chart or self._needs_chart(task)

        chart_instruction = ""
        if needs_chart:
            chart_instruction = """
IMPORTANT: You MUST use matplotlib to create the requested charts.
Always import matplotlib.pyplot as plt at the top.
Always call plt.figure() before plotting.
Always call plt.savefig("chart.png") at the end - DO NOT call plt.show().
Create the chart using the df variable which contains the CSV data.
"""

        prompt = f"""
You are a Python data analyst. Write Python code to complete this task:
Task: {task}

The data summary is:
{file_summary}

The data is available as a pandas DataFrame called 'df' with these columns:
{columns}

{chart_instruction}

Rules:
- Use only: pandas (pd), matplotlib (plt), the df variable
- Do NOT import csv, os, or open any files
- Do NOT use plt.show() - use plt.savefig() instead
- Print key results using print()
- Keep the code concise and correct

Write ONLY the Python code, no explanation, no markdown backticks.
"""
        data_preview = self._preview_file_data(file_data)

        response = self.llm.invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=f"Rows sample:\n{rows[:10] if isinstance(rows, list) else data_preview}"),
            ]
        )
        return self._strip_code_fence(str(response.content).strip())

    def __call__(
        self, task: str, file_data: dict[str, Any] | None = None, file_path: str | None = None
    ) -> dict[str, Any]:
        """Run analysis when the agent instance is called directly."""

        return self.run(task=task, file_data=file_data, file_path=file_path)

    def _is_safe_code(self, code: str) -> bool:
        """Return False when the code contains dangerous patterns."""

        return not any(pattern in code for pattern in _BLOCKED_PATTERNS)

    def _preview_file_data(self, file_data: dict[str, Any] | None) -> str:
        """Build a compact text preview for the code-generation prompt."""

        if not file_data:
            return "No file data provided."

        columns = file_data.get("columns", [])
        rows = file_data.get("rows", [])
        summary = file_data.get("summary", "")
        return (
            f"Summary: {summary}\n"
            f"Columns: {columns}\n"
            f"Rows sample: {rows[:10] if isinstance(rows, list) else rows}"
        )

    def _strip_code_fence(self, content: str) -> str:
        """Remove common markdown code fences from LLM output."""

        if not content.startswith("```"):
            return content

        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _needs_chart(self, task: str) -> bool:
        """Return True when the task explicitly asks for a visual chart."""

        return any(word in task.lower() for word in ["chart", "graph", "plot", "visualize", "bar", "line", "pie"])

    def _contains_chart_code(self, code: str) -> bool:
        """Return True when generated code uses matplotlib."""

        return "matplotlib" in code or "plt." in code

    def _save_chart(self, images: list[bytes]) -> str | None:
        """Store the first image produced in the sandbox under uploads/."""

        if not images:
            return None
        _CHART_DIR.mkdir(parents=True, exist_ok=True)
        path = _CHART_DIR / f"chart_{uuid.uuid4()}.png"
        path.write_bytes(images[0])
        return path.as_posix()

    def _fallback_chart_code(self, file_data: dict[str, Any] | None) -> str:
        """Generate a minimal matplotlib chart when the LLM ignores chart instructions."""

        columns = (file_data or {}).get("columns", [])
        category_column = "category" if "category" in columns else columns[0] if columns else None
        value_column = "total" if "total" in columns else "sales" if "sales" in columns else None
        if value_column is None:
            numeric_candidates = [column for column in columns if column not in {"order_id", "date", "product", "category"}]
            value_column = numeric_candidates[-1] if numeric_candidates else None

        if not category_column or not value_column:
            return (
                "import matplotlib.pyplot as plt\n"
                "df = pd.DataFrame(file_data.get('rows', []), columns=file_data.get('columns', []))\n"
                "plt.figure()\n"
                "df.count().plot(kind='bar')\n"
                "plt.title('Data overview')\n"
                "plt.tight_layout()\n"
                "plt.savefig('chart.png')\n"
                "print('Generated a data overview chart.')"
            )

        return (
            "import matplotlib.pyplot as plt\n"
            "df = pd.DataFrame(file_data.get('rows', []), columns=file_data.get('columns', []))\n"
            f"grouped = df.groupby('{category_column}')['{value_column}'].sum().sort_values(ascending=False)\n"
            "plt.figure()\n"
            "grouped.plot(kind='bar')\n"
            f"plt.title('{value_column} by {category_column}')\n"
            f"plt.xlabel('{category_column}')\n"
            f"plt.ylabel('{value_column}')\n"
            "plt.tight_layout()\n"
            "plt.savefig('chart.png')\n"
            "print(grouped.head(10).to_string())"
        )
