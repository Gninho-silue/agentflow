"""Scripted LLM responses and helpers shared by backend tests."""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel

PLAN_WITH_FILE = (
    '{"subtasks": ["Read the CSV", "Compute totals", "Write report"], '
    '"agents_needed": ["file_agent", "code_agent", "reporter"], '
    '"execution_order": ["file_agent", "code_agent", "reporter"]}'
)
PLAN_WITHOUT_FILE = (
    '{"subtasks": ["Compute the answer", "Write report"], '
    '"agents_needed": ["code_agent", "reporter"], '
    '"execution_order": ["code_agent", "reporter"]}'
)
REPORT = "# Summary\n\nFake report.\n\n## Key Findings\n\nAll good."


def fake_llm(*responses: str) -> FakeListChatModel:
    """Return a chat model that replies with the given scripted responses, in order."""

    return FakeListChatModel(responses=list(responses))
