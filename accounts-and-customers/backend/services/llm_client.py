"""LLM client for the Accounts & Customers AI-Mode features.

Both supported providers speak the OpenAI chat-completions protocol, so the
same client code drives either one. Switch providers with the LLM_PROVIDER
environment variable - nothing else in the codebase needs to change.

    LLM_PROVIDER=gemini  -> Google AI Studio free tier (day-to-day development)
    LLM_PROVIDER=ollama  -> local Llama / Qwen models via Ollama (required for
                             the Release 0 "Ollama Runtime" / AI-Mode rubric item)

See .env.example at the project root for the full list of provider settings.
"""

import os

from openai import OpenAI

_client = None
_client_provider = None


def _provider():
    return os.getenv("LLM_PROVIDER", "gemini").strip().lower()


def _provider_config(provider):
    if provider == "ollama":
        return {
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            "api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
        }

    # Default: gemini
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
    provider = _provider()

    if _client is None or _client_provider != provider:
        config = _provider_config(provider)
        if not config["api_key"] and provider != "ollama":
            raise RuntimeError(
                f"No API key configured for LLM_PROVIDER={provider!r}. "
                "Set GEMINI_API_KEY (or switch LLM_PROVIDER=ollama) in your environment."
            )
        _client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        _client_provider = provider

    return _client


def create_chat_completion(messages, max_tokens=400, temperature=0.2, model=None):
    provider = _provider()
    config = _provider_config(provider)
    client = _get_client()

    response = client.chat.completions.create(
        model=model or config["model"],
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content
