"""Grounded generation through the team's shared LLM client.

Reuses `agentic/llm.py` (Gemini by default, Ollama by LLM_PROVIDER) and the
team's prompt loader, so the RAG server has no provider code of its own and
its prompts live in `prompts/_rag/` as text files like everything else.
"""

from __future__ import annotations

from agentic import llm, prompts
from rag_server import config
from rag_server.retriever import EvidenceRecord

PROMPT_FAMILY = "_rag"
INSUFFICIENT_TOKEN = "INSUFFICIENT_CONTEXT"


class GenerationUnavailable(Exception):
    """The LLM provider could not be reached or is not configured."""


def context_block(evidence: list[EvidenceRecord]) -> str:
    return "\n\n".join(
        f"[{e.chunk_id}] (source: {e.title}, authority tier {e.authority_tier}"
        + (f", section: {e.heading}" if e.heading else "") + ")\n" + e.text
        for e in evidence
    )


def answer(query: str, evidence: list[EvidenceRecord], feedback: str = "") -> tuple[str, str]:
    """Returns (answer_text, model_description). Raises GenerationUnavailable."""
    try:
        system_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY, "answer_system.txt", "answer_task.txt"
        )
    except prompts.MissingPrompt as exc:
        raise GenerationUnavailable(str(exc)) from None

    correction = ""
    if feedback:
        correction = f"\n\nYour previous answer was rejected: {feedback}. Fix exactly that."

    user_prompt = (
        f"{task_prompt}{correction}\n\n"
        f"Context chunks:\n{context_block(evidence)}\n\n"
        f"Question: {query}"
    )
    try:
        text = llm.ask(
            system_prompt, user_prompt,
            max_tokens=config.MAX_ANSWER_TOKENS, temperature=config.ANSWER_TEMPERATURE,
        )
    except llm.LLMUnavailable as exc:
        raise GenerationUnavailable(str(exc)) from None
    return text.strip(), llm.describe()


def model_description() -> str:
    return llm.describe()
