"""Restricted Python execution helper for generated analysis code."""

from __future__ import annotations

import contextlib
import io
import math
import re
import statistics
from typing import Any

import pandas as pd


class CodeExecutor:
    """Execute generated Python with a conservative runtime environment."""

    def execute(self, code: str, file_data: dict[str, Any] | None = None) -> str:
        """Run Python code and return captured stdout."""

        stdout = io.StringIO()
        globals_dict: dict[str, Any] = {
            "__builtins__": self._safe_builtins(),
            "file_data": file_data or {},
            "math": math,
            "pd": pd,
            "pandas": pd,
            "re": re,
            "statistics": statistics,
        }
        locals_dict: dict[str, Any] = {}

        with contextlib.redirect_stdout(stdout):
            exec(code, globals_dict, locals_dict)

        return stdout.getvalue().strip()

    def _safe_builtins(self) -> dict[str, Any]:
        """Return the allowed builtins for generated code."""

        return {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "print": print,
            "range": range,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
            "__import__": self._safe_import,
        }

    def _safe_import(
        self,
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """Allow imports only for modules useful in local data analysis."""

        allowed_modules: dict[str, Any] = {
            "math": math,
            "pandas": pd,
            "re": re,
            "statistics": statistics,
        }
        root_name = name.split(".", maxsplit=1)[0]
        if root_name not in allowed_modules:
            raise ImportError(f"Import of '{name}' is not allowed in the AgentFlow sandbox.")
        return allowed_modules[root_name]
