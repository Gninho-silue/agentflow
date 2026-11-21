"""Entry point used by agents to run generated analysis code.

The code never runs in the server process: it is delegated to a ``Sandbox``
(by default a locked-down subprocess, see ``backend.sandbox``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from backend.observability import SANDBOX_DURATION, SANDBOX_RUNS, logger
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

        started = time.perf_counter()
        result = self.sandbox.run(code, file_data=file_data, input_files=input_files)
        elapsed = time.perf_counter() - started
        outcome = "timeout" if result.timed_out else "ok" if result.ok else "error"
        SANDBOX_RUNS.labels(outcome).inc()
        SANDBOX_DURATION.observe(elapsed)
        logger.info(
            "Sandbox run %s in %.2fs",
            outcome,
            elapsed,
            extra={"sandbox_outcome": outcome, "error_type": result.error_type},
        )
        return result

    def execute(self, code: str, file_data: dict[str, Any] | None = None) -> str:
        """Run code and return its stdout, raising ``SandboxExecutionError`` on failure."""

        result = self.run(code, file_data)
        if not result.ok:
            raise SandboxExecutionError(result)
        return result.stdout
