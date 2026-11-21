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


# --- Availability check -----------------------------------------------------


def test_check_llm_ok_when_ollama_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Ok:
        status = 200

        def __enter__(self) -> "Ok":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(url: str, timeout: float) -> Ok:
        calls.append(url)
        return Ok()

    monkeypatch.setattr(llm_module, "urlopen", fake_urlopen)
    assert llm_module.check_llm() is None
    assert calls == ["http://localhost:11434/api/tags"]


def test_check_llm_explains_unreachable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, timeout: float) -> None:
        raise ConnectionRefusedError("[WinError 10061] refused")

    monkeypatch.setattr(llm_module, "urlopen", refuse)
    message = llm_module.check_llm()
    assert message is not None
    assert "Ollama is not reachable at http://localhost:11434" in message
    assert "ollama serve" in message
    assert "WinError" not in message


def test_check_llm_reports_configuration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert "GROQ_API_KEY" in (llm_module.check_llm() or "")


def test_check_llm_trusts_groq_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    assert llm_module.check_llm() is None
