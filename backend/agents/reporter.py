"""Reporter agent for producing final markdown task reports."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from backend.llm import get_llm

from backend.graph.state import AgentState


class ReporterAgent:
    """Aggregate workflow outputs into a clean markdown report."""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        """Create a reporter; the model comes from ``backend.llm.get_llm`` unless injected."""

        self.llm = llm or get_llm()

    def write_report(self, state: AgentState) -> str:
        """Use the LLM to write a final markdown report from AgentState."""

        try:
            response = self.llm.invoke(
                [
                    SystemMessage(content=self._system_prompt()),
                    HumanMessage(content=self._state_prompt(state)),
                ]
            )
            report = str(response.content).strip()
            return self._finalize(report or self._fallback_report(state), state)
        except Exception:
            return self._finalize(self._fallback_report(state), state)

    def __call__(self, state: AgentState) -> str:
        """Write a report when the agent instance is called directly."""

        return self.write_report(state)

    def _system_prompt(self) -> str:
        """Return the report-generation instructions."""

        return (
            "You are the ReporterAgent for AgentFlow. "
            "Write a clean markdown report with exactly these sections: "
            "Summary, Data Analysis, Key Findings, Conclusion. "
            "Be concise, factual, and base the report only on provided data. "
            "Quote the exact numbers from the code output instead of rounding them into words. "
            "Use 'majority' or 'most' only for a share strictly more than 50%; "
            "50% is 'half', and the largest group below 50% is 'the largest group' or 'a plurality'. "
            "Never list CSV column names as separate code blocks. "
            "List them inline as: `order_id`, `date`, `product`, etc. "
            "Never write placeholder text such as '[Insert chart]', "
            "'[Chart goes here]', or any similar stand-in. "
            "If the Chart path in the provided state is a real file path, "
            "include the chart as a markdown image using the exact tag: "
            "![Chart](/<chart_filename>) where <chart_filename> is the "
            "basename of the path prefixed with 'uploads/' "
            "(e.g. ![Chart](/uploads/chart_abc123.png)). "
            "If Chart path is None or empty, write nothing about a chart — "
            "do not mention it at all."
        )

    def _state_prompt(self, state: AgentState) -> str:
        """Serialize relevant workflow state for the LLM."""

        return (
            f"Original task:\n{state.get('task')}\n\n"
            f"Subtasks:\n{state.get('subtasks')}\n\n"
            f"File data:\n{self._compact(state.get('file_data'))}\n\n"
            f"Code output:\n{state.get('code_output')}\n\n"
            f"Chart path:\n{self._chart_path(state)}\n\n"
            f"Code attempts:\n{self._attempts_summary(state)}\n\n"
            f"Error:\n{state.get('error')}"
        )

    def _finalize(self, report: str, state: AgentState) -> str:
        """Add the deterministic sections the LLM must not be trusted to write."""

        return self._append_code_failure(self._append_chart(report, state), state)

    def _failed_attempts(self, state: AgentState) -> list[dict[str, Any]] | None:
        """Return the attempts when the CodeAgent ended in failure, else None."""

        attempts = state.get("code_attempts") or []
        if attempts and attempts[-1].get("error"):
            return attempts
        return None

    def _attempts_summary(self, state: AgentState) -> str:
        """One line per CodeAgent attempt, for the LLM prompt."""

        attempts = state.get("code_attempts") or []
        if not attempts:
            return "None"
        return "\n".join(
            f"- attempt {a.get('attempt')}: "
            + (f"failed: {a['error']}" if a.get("error") else "succeeded")
            for a in attempts
        )

    def _append_code_failure(self, report: str, state: AgentState) -> str:
        """Say clearly in the report that the analysis code could not run."""

        attempts = self._failed_attempts(state)
        if not attempts:
            return report
        count = len(attempts)
        plural = "s" if count != 1 else ""
        return (
            f"{report.rstrip()}\n\n"
            "## Code execution failed\n\n"
            f"The generated analysis code still failed after {count} attempt{plural} "
            "(automatic self-correction). The findings above are not backed by computed results.\n\n"
            f"Last error:\n\n```\n{attempts[-1].get('error')}\n```"
        )

    def _compact(self, value: Any) -> Any:
        """Limit large row payloads before sending them to the LLM."""

        if not isinstance(value, dict):
            return value

        compacted = value.copy()
        rows = compacted.get("rows")
        if isinstance(rows, list):
            compacted["rows"] = rows[:10]
        return compacted

    def _chart_path(self, state: AgentState) -> str | None:
        """Return chart path from state or CodeAgent output metadata."""

        chart_path = state.get("chart_path")
        if chart_path:
            return str(chart_path)

        code_output = state.get("code_output") or ""
        marker = "[chart_path]:"
        if marker not in code_output:
            return None
        return code_output.split(marker, maxsplit=1)[1].strip().splitlines()[0].strip()

    def _append_chart(self, report: str, state: AgentState) -> str:
        """Append chart markdown when chart generation produced an image."""

        chart_path = self._chart_path(state)
        if not chart_path:
            return report

        chart_url = "/" + chart_path.replace("\\", "/").lstrip("/")
        if chart_url in report:
            return report

        return (
            f"{report.rstrip()}\n\n"
            "## Analysis Chart\n\n"
            f'<img src="{chart_url}" alt="Analysis Chart" />'
        )

    def _fallback_report(self, state: AgentState) -> str:
        """Create a deterministic report if the local LLM is unavailable."""

        file_data = state.get("file_data") or {}
        file_summary = file_data.get("summary", "No file data was provided.")
        columns = file_data.get("columns", [])
        columns_text = ""
        if isinstance(columns, list) and columns:
            inline_columns = ", ".join(f"`{column}`" for column in columns)
            columns_text = f"\n\nDetected columns: {inline_columns}."
        code_output = state.get("code_output") or "No code output was produced."
        chart_path = self._chart_path(state)
        chart_section = ""
        if chart_path:
            chart_url = "/" + chart_path.replace("\\", "/").lstrip("/")
            chart_section = f'\n\n## Analysis Chart\n\n<img src="{chart_url}" alt="Analysis Chart" />'

        return (
            "# Summary\n\n"
            f"{state.get('task')}\n\n"
            "## Data Analysis\n\n"
            f"{file_summary}{columns_text}\n\n"
            "## Key Findings\n\n"
            f"{code_output}\n\n"
            "## Conclusion\n\n"
            "AgentFlow completed the available workflow steps and generated this report."
            f"{chart_section}"
        )
