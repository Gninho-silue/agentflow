"""Isolated execution of LLM-generated code."""

from backend.sandbox.base import Sandbox, SandboxResult
from backend.sandbox.subprocess_sandbox import SubprocessSandbox


def get_sandbox() -> Sandbox:
    """Return the sandbox used by the agents (only the local one exists today)."""

    return SubprocessSandbox()


__all__ = ["Sandbox", "SandboxResult", "SubprocessSandbox", "get_sandbox"]
