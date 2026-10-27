"""LLM client for the Transactions feature (simple wrapper).

This mirrors the other feature LLM clients but is intentionally small — it
selects provider from `LLM_PROVIDER` and exposes `create_chat_completion`.
"""

import os

from openai import OpenAI

_client = None
_client_provider = None


def provider():
    return os.getenv("LLM_PROVIDER", "gemini").strip().lower()


def _provider_config(name):
    if name == "ollama":
        return {
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            "api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
        }

    return {
        "base_url": os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    }


def _get_client():
    global _client, _client_provider
    name = provider()

    if _client is None or _client_provider != name:
        config = _provider_config(name)
        if not config["api_key"] and name != "ollama":
            raise RuntimeError(
                f"No API key configured for LLM_PROVIDER={name!r}."
            )
        _client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        _client_provider = name

    return _client


def create_chat_completion(messages, max_tokens=400, temperature=0.2, model=None):
    config = _provider_config(provider())
    client = _get_client()

    response = client.chat.completions.create(
        model=model or config["model"],
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content
