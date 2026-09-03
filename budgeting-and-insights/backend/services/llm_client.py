"""Ollama client for AI-Mode.

Release 0 requires the Frontend -> Backend/API -> Ollama -> LLM workflow using
an approved open-source model (Qwen, Llama or DeepSeek). This client calls
Ollama's native /api/generate endpoint.
"""

import os

import requests


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))


def get_model():
    return OLLAMA_MODEL


def generate(prompt, system=None, model=None, max_tokens=500, temperature=0.2):
    """Send a prompt to Ollama and return the generated text."""
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if system:
        payload["system"] = system

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_URL}. Is the ollama service running "
            f"and the model pulled? ({exc})"
        ) from exc

    if response.status_code == 404:
        raise RuntimeError(
            f"Ollama has no model named '{payload['model']}'. "
            f"Pull it first: ollama pull {payload['model']}"
        )

    response.raise_for_status()

    body = response.json()
    text = (body.get("response") or "").strip()

    if not text:
        raise RuntimeError("Ollama returned an empty response")

    return text
