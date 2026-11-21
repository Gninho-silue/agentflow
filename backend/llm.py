"""Single place where the chat model is chosen.

- ``LLM_PROVIDER``: ``ollama`` (default, fully local) or ``groq`` (hosted demo).
- ``LLM_MODEL``: model name; defaults per provider (see ``DEFAULT_MODELS``).
  ``OLLAMA_MODEL`` is still accepted for backward compatibility.
- ``OLLAMA_HOST``: Ollama server URL (default ``http://localhost:11434``).
- ``GROQ_API_KEY``: required with ``groq``; read from the environment only.
"""

from __future__ import annotations

import os

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
