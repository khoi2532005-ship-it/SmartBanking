import os

from openai import OpenAI

_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
)
_API_KEY = os.getenv("GEMINI_API_KEY", "")
_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


client = OpenAI(base_url=_BASE_URL, api_key=_API_KEY)


def create_chat_completion(messages, max_tokens=400, temperature=0.2, model=None):
    response = client.chat.completions.create(
        model=model or _MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content
