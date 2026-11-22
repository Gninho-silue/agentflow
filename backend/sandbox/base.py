"""Sandbox interface for running LLM-generated Python code.

Agents only depend on this interface, so the local subprocess implementation
can later be swapped for a hosted service (E2B, etc.) without touching them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one sandboxed execution."""

    ok: bool
    stdout: str = ""
    error: str | None = None
    error_type: str | None = None
    traceback: str | None = None
    timed_out: bool = False
    # PNG images produced by the code (open matplotlib figures or *.png files).
    images: list[bytes] = field(default_factory=list)
    # Per-category numbers the code computed: {indicator: {category: value}}.
    indicators: dict[str, dict[str, float]] = field(default_factory=dict)


class Sandbox(Protocol):
    """Runs untrusted Python code away from the server process."""

    def run(
        self,
        code: str,
        file_data: dict[str, Any] | None = None,
        input_files: list[Path] | None = None,
    ) -> SandboxResult:
        """Execute ``code`` and return its output.

        ``file_data`` is exposed to the code as ``file_data`` and ``df``;
        ``input_files`` are *copied* into the working directory.
        """
        ...
