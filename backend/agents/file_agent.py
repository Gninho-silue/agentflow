"""File agent for reading uploaded CSV, JSON, and TXT files."""

from __future__ import annotations

from typing import Any

from backend.tools.file_tools import read_structured_file


class FileAgent:
    """Parse supported uploaded files into structured data summaries."""

    def read_file(self, file_path: str) -> dict[str, Any]:
        """Read a CSV, JSON, or TXT file and return structured metadata."""

        try:
            return read_structured_file(file_path)
        except UnicodeDecodeError as exc:
            return self._error_result(f"Could not decode file. Try uploading UTF-8 text. {exc}")
        except Exception as exc:
            return self._error_result(str(exc))

    def __call__(self, file_path: str) -> dict[str, Any]:
        """Read a file when the agent instance is called directly."""

        return self.read_file(file_path)

    def _error_result(self, message: str) -> dict[str, Any]:
        """Return the standard file data shape for read failures."""

        return {
            "columns": [],
            "rows": [],
            "summary": f"File processing failed: {message}",
            "row_count": 0,
            "error": message,
        }
