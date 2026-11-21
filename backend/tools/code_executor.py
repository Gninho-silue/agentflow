"""Entry point used by agents to run generated analysis code.

The code never runs in the server process: it is delegated to a ``Sandbox``
(by default a locked-down subprocess, see ``backend.sandbox``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.sandbox import Sandbox, SandboxResult, get_sandbox


class SandboxExecutionError(RuntimeError):
    """Raised by ``CodeExecutor.execute`` when the generated code fails."""

    def __init__(self, result: SandboxResult) -> None:
        super().__init__(result.error or "Execution failed.")
        self.result = result


class CodeExecutor:
    """Run generated Python through a sandbox."""

    def __init__(self, sandbox: Sandbox | None = None) -> None:
        self.sandbox = sandbox or get_sandbox()

    def run(
        self,
        code: str,
        file_data: dict[str, Any] | None = None,
        input_files: list[Path] | None = None,
    ) -> SandboxResult:
        """Run code and return the full result (stdout, error, traceback, images)."""

        return self.sandbox.run(code, file_data=file_data, input_files=input_files)

    def execute(self, code: str, file_data: dict[str, Any] | None = None) -> str:
        """Run code and return its stdout, raising ``SandboxExecutionError`` on failure."""

        result = self.run(code, file_data)
        if not result.ok:
            raise SandboxExecutionError(result)
        return result.stdout
