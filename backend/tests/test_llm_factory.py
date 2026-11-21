"""LLM provider selection (no network: models are only constructed, never called)."""

from __future__ import annotations

import pytest

from backend import llm as llm_module
from backend.llm import DEFAULT_MODELS, LLMConfigError, get_llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_PROVIDER", "LLM_MODEL", "OLLAMA_MODEL", "OLLAMA_HOST", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_local_ollama() -> None:
    from langchain_ollama import ChatOllama

    model = get_llm()
    assert isinstance(model, ChatOllama)
    assert model.model == DEFAULT_MODELS["ollama"] == "llama3.2:1b"


def test_llm_model_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "llama3.2:3b")
    assert get_llm().model == "llama3.2:3b"


def test_legacy_ollama_model_variable_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    assert get_llm().model == "mistral"


def test_ollama_host_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    assert get_llm().base_url == "http://host.docker.internal:11434"


def test_provider_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", " Ollama ")
    assert get_llm().model == "llama3.2:1b"


def test_groq_without_api_key_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
        get_llm()


def test_groq_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_groq import ChatGroq

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    model = get_llm()
    assert isinstance(model, ChatGroq)
    assert model.model_name == DEFAULT_MODELS["groq"]
    assert model.temperature < 1e-6  # ChatGroq stores 0 as 1e-8


def test_unknown_provider_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(LLMConfigError, match="ollama, groq"):
        get_llm()


def test_agents_use_the_factory_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.agents.code_agent import CodeAgent
    from backend.agents.planner import PlannerAgent
    from backend.agents.reporter import ReporterAgent
    from backend.graph import workflow

    sentinel = object()
    for module in ("backend.agents.code_agent", "backend.agents.planner", "backend.agents.reporter"):
        monkeypatch.setattr(f"{module}.get_llm", lambda: sentinel)
    assert PlannerAgent().llm is sentinel
    assert CodeAgent().llm is sentinel
    assert ReporterAgent().llm is sentinel

    calls: list[int] = []
    monkeypatch.setattr(workflow, "get_llm", lambda: calls.append(1) or llm_module.get_llm())
    workflow.create_workflow()
    assert calls == [1]
