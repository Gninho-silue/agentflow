"""Reusable file parsing helpers for AgentFlow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_structured_file(file_path: str) -> dict[str, Any]:
    """Read a CSV, JSON, or TXT file into AgentFlow's standard shape."""

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv(path)
    if suffix == ".json":
        return read_json(path)
    if suffix == ".txt":
        return read_txt(path)
    raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")


def read_csv(path: Path) -> dict[str, Any]:
    """Read a CSV file with pandas and summarize its contents."""

    dataframe = pd.read_csv(path, encoding="utf-8")
    rows = dataframe.head(100).where(pd.notnull(dataframe), None).to_dict(orient="records")
    columns = [str(column) for column in dataframe.columns]
    return {
        "columns": columns,
        "rows": rows,
        "summary": (
            f"CSV file with {len(dataframe)} rows and {len(columns)} columns. "
            f"Columns: {', '.join(columns) if columns else 'none'}."
        ),
        "row_count": int(len(dataframe)),
    }


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file and normalize the top-level payload into rows."""

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, list):
        rows = data[:100]
        columns = _columns_from_rows(rows)
        row_count = len(data)
    elif isinstance(data, dict):
        rows = [data]
        columns = [str(key) for key in data.keys()]
        row_count = 1
    else:
        rows = [{"value": data}]
        columns = ["value"]
        row_count = 1

    return {
        "columns": columns,
        "rows": rows,
        "summary": (
            f"JSON file with {row_count} top-level row"
            f"{'' if row_count == 1 else 's'} and {len(columns)} detected fields."
        ),
        "row_count": int(row_count),
    }


def read_txt(path: Path) -> dict[str, Any]:
    """Read a TXT file and expose line-oriented rows."""

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    return {
        "columns": ["line_number", "text"],
        "rows": [{"line_number": index + 1, "text": line} for index, line in enumerate(lines[:100])],
        "summary": f"TXT file with {len(lines)} lines and {len(content)} characters.",
        "row_count": int(len(lines)),
    }


def _columns_from_rows(rows: list[Any]) -> list[str]:
    """Collect field names from dictionary rows."""

    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            column = str(key)
            if column not in seen:
                seen.add(column)
                columns.append(column)
    return columns
