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

AI_MODE_ENABLED=false (Release 2, the same switch fraud reads) turns AI-Mode
off: no model call is made, the insight endpoints answer 503 and the panels
say so. CI and the cloud baseline set it; CRUD is unaffected.
"""

import os
import sys

from openai import OpenAI

_client = None
_client_provider = None

DISABLED_MESSAGE = "AI-Mode is switched off in this environment (AI_MODE_ENABLED=false)"
PROVIDER_NAMES = {"gemini": "Gemini", "ollama": "Ollama"}


class AIModeDisabled(RuntimeError):
    """AI_MODE_ENABLED is off (CI, the cloud baseline): no model call is made."""


def enabled():
    """AI-Mode's own switch, read per call like MCP_ENABLED."""
    return os.getenv("AI_MODE_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def provider():
    return os.getenv("LLM_PROVIDER", "gemini").strip().lower()


def provider_name():
    """The provider as a person reads it, for the insight card."""
    return PROVIDER_NAMES.get(provider(), provider())


def status():
    """Configuration only, never a model call: what /api/agents/status and the panel show."""
    return {"enabled": enabled(), "provider": provider(), "model": get_model()}


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
        "model": os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
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


def create_chat_completion(messages, max_tokens=4000, temperature=0.2, model=None):
    """Send a chat completion and return the text of the first choice.

    Gemini 3.x models reason before answering, and those hidden reasoning
    tokens count against max_tokens. Two things keep the visible reply from
    being truncated: a generous max_tokens ceiling (only tokens actually
    used are billed) and asking for low reasoning effort, which is plenty
    for short plain-English explanations. Ollama ignores reasoning_effort.

    Raises RuntimeError when the provider is unreachable, rejects the request,
    or returns an empty message, so callers can map any failure to one
    503 response. With AI-Mode switched off it raises AIModeDisabled (a
    RuntimeError too) before any client is built.
    """
    if not enabled():
        raise AIModeDisabled(DISABLED_MESSAGE)
    config = _provider_config(provider())
    client = _get_client()

    request = {
        "model": model or config["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if provider() == "gemini":
        request["reasoning_effort"] = os.getenv("GEMINI_REASONING_EFFORT", "low")

    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:  # network, auth, rate limit, bad model
        raise RuntimeError(
            f"{provider()} request failed ({exc.__class__.__name__}): {exc}"
        ) from exc

    choice = response.choices[0]
    text = (choice.message.content or "").strip()
    if not text:
        raise RuntimeError(f"{provider()} returned an empty response")

    if choice.finish_reason == "length":
        # Visible text was cut off. Surface it in the logs rather than
        # silently returning half a sentence to the user.
        usage = getattr(response, "usage", None)
        print(
            f"[llm_client] WARNING: {provider()} hit max_tokens={max_tokens} "
            f"(completion_tokens={getattr(usage, 'completion_tokens', '?')}); "
            "reply is truncated",
            file=sys.stderr,
        )

    return text
