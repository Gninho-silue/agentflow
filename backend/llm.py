"""Single place where the chat model is chosen.

- ``LLM_PROVIDER``: ``ollama`` (default, fully local) or ``groq`` (hosted demo).
- ``LLM_MODEL``: model name; defaults per provider (see ``DEFAULT_MODELS``).
  ``OLLAMA_MODEL`` is still accepted for backward compatibility.
- ``OLLAMA_HOST``: Ollama server URL (default ``http://localhost:11434``).
- ``GROQ_API_KEY``: required with ``groq``; read from the environment only.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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

    Ollama is probed with ``GET /api/tags``; Groq with ``GET /openai/v1/models``,
    which checks the key and that the model still exists without spending tokens.
    """

    try:
        get_llm()
    except LLMConfigError as exc:
        return str(exc)

    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    if provider == "groq":
        return _check_groq()

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


_GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"


def _check_groq() -> str | None:
    model = os.getenv("LLM_MODEL") or DEFAULT_MODELS["groq"]
    request = Request(  # noqa: S310 - fixed https URL
        _GROQ_MODELS_URL,
        headers={
            "Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '').strip()}",
            # Cloudflare in front of Groq refuses urllib's default agent with a 403.
            "User-Agent": "AgentFlow/1.0 (+https://github.com/Gninho-silue/agentflow)",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310
            payload = json.loads(response.read())
    except HTTPError as exc:
        if exc.code == 401:
            return "The GROQ_API_KEY was rejected by Groq. Create a new key in the Groq console."
        return f"The Groq API answered with HTTP {exc.code}."
    except Exception:  # noqa: BLE001 - network failure, invalid JSON...
        return "The Groq API is not reachable right now. Try again in a moment."

    available = sorted(str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict))
    if model not in available:
        return (
            f"The model '{model}' is not available on Groq. Set LLM_MODEL to one of: "
            f"{', '.join(available) or 'none listed'}."
        )
    return None
