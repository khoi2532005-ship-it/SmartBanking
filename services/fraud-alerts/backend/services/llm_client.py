import os

from openai import OpenAI

_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

if _PROVIDER == "ollama":
    _BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    _API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")
    _MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
    _KEY_VAR = "OLLAMA_API_KEY"
else:
    _BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    _API_KEY = os.getenv("GEMINI_API_KEY", "")
    _MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    _KEY_VAR = "GEMINI_API_KEY"

_client = None


# The SDK's own default (~600s) is far too long for a request a browser is
# waiting on - a slow or rate-limited call should fail fast into the
# degraded-explanation path instead of hanging the whole HTTP request.
REQUEST_TIMEOUT = 20


def _get_client():
    global _client
    if _client is None:
        if not _API_KEY:
            raise RuntimeError(
                f"{_KEY_VAR} is not set. Set it in your environment to use AI features."
            )
        _client = OpenAI(base_url=_BASE_URL, api_key=_API_KEY, timeout=REQUEST_TIMEOUT)
    return _client


_RATE_LIMITED = ("the AI provider's rate limit was reached (on Gemini's free tier one per-minute "
                 "quota is shared by everything using the key). Wait a minute and try again.")
MAX_ERROR_LENGTH = 300


def describe_error(error):
    """A short reason for a failed LLM call that is fit to show a person.

    A rate-limited Gemini call raises a 429 whose message is a page of JSON;
    the full error still goes to the log, the page gets one sentence."""
    text = str(error)
    if "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        return _RATE_LIMITED
    return text if len(text) <= MAX_ERROR_LENGTH else text[:MAX_ERROR_LENGTH] + "..."


def create_chat_completion(messages, max_tokens=4000, temperature=0.2, model=None):
    response = _get_client().chat.completions.create(
        model=model or _MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content
