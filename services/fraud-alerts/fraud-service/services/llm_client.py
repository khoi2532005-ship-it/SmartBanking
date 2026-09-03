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
    _MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    _KEY_VAR = "GEMINI_API_KEY"

_client = None


def _get_client():
    global _client
    if _client is None:
        if not _API_KEY:
            raise RuntimeError(
                f"{_KEY_VAR} is not set. Set it in your environment to use AI features."
            )
        _client = OpenAI(base_url=_BASE_URL, api_key=_API_KEY)
    return _client


def create_chat_completion(messages, max_tokens=400, temperature=0.2, model=None):
    response = _get_client().chat.completions.create(
        model=model or _MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content
