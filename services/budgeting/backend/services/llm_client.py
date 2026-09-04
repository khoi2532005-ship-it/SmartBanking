"""LLM client for the Budgeting & Spending Insights AI-Mode features.

Both supported providers speak the OpenAI chat-completions protocol, so the
same client code drives either one. Switch providers with the LLM_PROVIDER
environment variable; nothing else in the codebase needs to change.

    LLM_PROVIDER=gemini  -> Google Gemini API (team default)
    LLM_PROVIDER=ollama  -> local Llama / Qwen models via Ollama, only with the
                             `local-llm` compose profile

See .env.example at the project root for the full list of provider settings.
This mirrors services/accounts/backend/services/llm_client.py so the
two can be merged into shared/python/smartbank_common later.
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

    # Default: gemini
    return {
        "base_url": os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    }


def get_model():
    return _provider_config(provider())["model"]


def _get_client():
    global _client, _client_provider
    name = provider()

    if _client is None or _client_provider != name:
        config = _provider_config(name)
        if not config["api_key"] and name != "ollama":
            raise RuntimeError(
                f"No API key configured for LLM_PROVIDER={name!r}. "
                "Set GEMINI_API_KEY (or switch LLM_PROVIDER=ollama) in your environment."
            )
        _client = OpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"],
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )
        _client_provider = name

    return _client


def create_chat_completion(messages, max_tokens=400, temperature=0.2, model=None):
    """Send a chat completion and return the text of the first choice.

    Raises RuntimeError when the provider is unreachable, rejects the request,
    or returns an empty message, so callers can map any failure to one
    503 response.
    """
    config = _provider_config(provider())
    client = _get_client()

    try:
        response = client.chat.completions.create(
            model=model or config["model"],
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:  # network, auth, rate limit, bad model
        raise RuntimeError(
            f"{provider()} request failed ({exc.__class__.__name__}): {exc}"
        ) from exc

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError(f"{provider()} returned an empty response")

    return text
