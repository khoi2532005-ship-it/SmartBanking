"""Provider-agnostic chat client for the agentic loop.

Gemini and Ollama both speak the OpenAI chat-completions protocol, so a single
client drives either one - flip `LLM_PROVIDER` in `.env` and nothing else
changes. This deliberately mirrors
`services/fraud-alerts/backend/services/llm_client.py`: same env var names,
same defaults, so there is one set of credentials to configure, not two.

The loop keeps the provider switch even though the tutor approved Gemini,
because Release 2 deploys AI-Mode to the cloud and a local Ollama fallback
costs nothing to keep working.
"""

from __future__ import annotations

import os

from openai import OpenAI

# The loop makes a handful of calls per run and a human is watching the
# terminal, so fail fast into the Adapt path rather than hanging a demo.
REQUEST_TIMEOUT = 30


class LLMUnavailable(RuntimeError):
    """Raised when the provider cannot be reached or is misconfigured.

    The engine catches this and records it as a failed attempt, so a missing
    API key degrades the run instead of crashing it mid-showcase.
    """


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "gemini").strip().lower()


def _settings() -> dict[str, str]:
    if _provider() == "ollama":
        return {
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            "api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
            "review_model": os.getenv("OLLAMA_REVIEW_MODEL", "llama3.1:8b"),
            "key_var": "OLLAMA_API_KEY",
        }
    return {
        "base_url": os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
        ),
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "model": os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
        "review_model": os.getenv("GEMINI_REVIEW_MODEL", "gemini-flash-lite-latest"),
        "key_var": "GEMINI_API_KEY",
    }


def describe(*, review: bool = False) -> str:
    """One line for the run header and the evidence log."""
    s = _settings()
    return f"{_provider()} / {s['review_model' if review else 'model']}"


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        s = _settings()
        if not s["api_key"]:
            raise LLMUnavailable(
                f"{s['key_var']} is not set. Copy .env.example to .env and fill it in."
            )
        _client = OpenAI(
            base_url=s["base_url"], api_key=s["api_key"], timeout=REQUEST_TIMEOUT
        )
    return _client


def ask(system_prompt: str, user_prompt: str, *, review: bool = False,
        max_tokens: int = 1000, temperature: float = 0.2) -> str:
    """Single chat call. Raises LLMUnavailable on any provider-side failure.

    `max_tokens` is deliberately generous: newer Gemini models spend part of
    the budget on hidden reasoning before the visible answer, and a tight cap
    truncates real answers mid-sentence even when the call itself succeeds.
    Truncated output then fails OBSERVE and burns a retry for no reason.
    """
    s = _settings()
    try:
        response = _get_client().chat.completions.create(
            model=s["review_model"] if review else s["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except LLMUnavailable:
        raise
    except Exception as exc:  # provider SDK raises a wide range of errors
        raise LLMUnavailable(f"{describe()} call failed: {exc}") from exc

    return (response.choices[0].message.content or "").strip()
