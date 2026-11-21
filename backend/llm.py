"""Single place where the chat model is chosen.

- ``LLM_PROVIDER``: ``ollama`` (default, fully local) or ``groq`` (hosted demo).
- ``LLM_MODEL``: model name; defaults per provider (see ``DEFAULT_MODELS``).
  ``OLLAMA_MODEL`` is still accepted for backward compatibility.
- ``OLLAMA_HOST``: Ollama server URL (default ``http://localhost:11434``).
- ``GROQ_API_KEY``: required with ``groq``; read from the environment only.
"""

from __future__ import annotations

import os
from urllib.request import urlopen

from langchain_core.language_models import BaseChatModel

PROVIDERS = ("ollama", "groq")
DEFAULT_MODELS = {
    "ollama": "llama3.2:1b",
    "groq": "llama-3.3-70b-versatile",
}


class LLMConfigError(RuntimeError):
    """Raised when the LLM environment variables are invalid or incomplete."""


def get_llm() -> BaseChatModel:
    """Build the chat model selected by the environment."""

    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    if provider not in PROVIDERS:
        raise LLMConfigError(
            f"Unknown LLM_PROVIDER '{provider}'. Supported providers: {', '.join(PROVIDERS)}."
        )

    model = os.getenv("LLM_MODEL") or (
        os.getenv("OLLAMA_MODEL") if provider == "ollama" else None
    ) or DEFAULT_MODELS[provider]

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise LLMConfigError(
                "LLM_PROVIDER=groq requires the GROQ_API_KEY environment variable. "
                "Set it in your shell or hosting dashboard (never commit it), "
                "or use LLM_PROVIDER=ollama to run fully locally."
            )
        from langchain_groq import ChatGroq

        return ChatGroq(model=model, api_key=api_key, temperature=0)

    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model,
        base_url=os.getenv("OLLAMA_HOST") or "http://localhost:11434",
    )


def check_llm() -> str | None:
    """Return None when the configured LLM looks usable, else a message for the user.

    Ollama is probed (``GET /api/tags``, 3 s timeout). Groq is not called: it
    is only checked for configuration, to avoid spending quota on health checks.
    """

    try:
        get_llm()
    except LLMConfigError as exc:
        return str(exc)

    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    if provider != "ollama":
        return None

    host = (os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    try:
        with urlopen(f"{host}/api/tags", timeout=3):  # noqa: S310 - configured host
            return None
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        model = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or DEFAULT_MODELS["ollama"]
        return (
            f"Ollama is not reachable at {host}. Start it with `ollama serve` "
            f"and make sure the model is installed (`ollama pull {model}`)."
        )
