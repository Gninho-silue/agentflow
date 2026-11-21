"""The example datasets shipped with the demo must be readable by the FileAgent."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.agents.file_agent import FileAgent

EXAMPLES = Path(__file__).resolve().parents[2] / "frontend" / "public" / "examples"

# The backend Docker image does not contain the frontend; the plain pytest job covers this.
pytestmark = pytest.mark.skipif(not EXAMPLES.is_dir(), reason="frontend examples not present")


@pytest.mark.parametrize(
    ("name", "columns", "rows"),
    [
        ("monthly_sales.csv", ["month", "region", "category", "units", "revenue"], 24),
        ("product_catalog.json", ["sku", "name", "category", "price", "stock", "rating"], 12),
        ("customer_reviews.txt", ["line_number", "text"], 18),
    ],
)
def test_example_dataset_is_parsed(name: str, columns: list[str], rows: int) -> None:
    data = FileAgent().read_file(str(EXAMPLES / name))

    assert "error" not in data
    assert data["columns"] == columns
    assert data["row_count"] == rows


def test_example_datasets_are_small() -> None:
    for path in EXAMPLES.iterdir():
        assert path.stat().st_size < 10_000, path.name
