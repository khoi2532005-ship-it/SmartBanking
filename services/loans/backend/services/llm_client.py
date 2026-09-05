import os

from openai import OpenAI

_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
)
_API_KEY = os.getenv("GEMINI_API_KEY", "")
_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

_client = None


def _get_client():
    global _client
    if _client is None:
        if not _API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Set it in your environment to use AI features."
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
