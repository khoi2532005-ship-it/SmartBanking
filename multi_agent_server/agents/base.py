"""Shared pieces of every agent: prompt loading, one model call, one bound.

Every role goes through the shared client in agentic/llm.py, so the Planner,
Worker and Reviewer use the same provider and credentials as AI-Mode. A
per-role model override (MULTI_AGENT_<ROLE>_MODEL) lets a demo give the
Reviewer a different model from the Planner without any code change.
"""

from __future__ import annotations

import threading
from string import Template
from typing import Any, Callable

from agentic import llm, prompts
from multi_agent_server import config

PROMPT_FAMILY = "_multi_agent"

# Signature every agent accepts for its model call, so tests and the validate
# script can script answers: ask(system_prompt, user_prompt, *, model, max_tokens, temperature) -> str
AskFn = Callable[..., str]


class StageTimeout(RuntimeError):
    """A stage did not answer within its bound (config.STAGE_TIMEOUT)."""


def load_prompts(role: str) -> tuple[str, Template]:
    """`prompts/_multi_agent/<role>_system.txt` and `<role>_task.txt` (a Template)."""
    system, task = prompts.load_all(PROMPT_FAMILY, f"{role}_system.txt", f"{role}_task.txt")
    return system, Template(task)


def model_for(role: str) -> str:
    """The provider/model line recorded against every stage of this role."""
    return llm.describe(model=config.role_model(role))


def call_model(role: str, system_prompt: str, user_prompt: str, *, ask: AskFn | None = None,
               max_tokens: int = 1500, temperature: float = 0.2) -> str:
    ask_fn = ask or llm.ask
    return ask_fn(system_prompt, user_prompt, model=config.role_model(role),
                  max_tokens=max_tokens, temperature=temperature)


def bounded(fn: Callable[[], Any], timeout: float, *, label: str) -> Any:
    """Run `fn` and wait at most `timeout` seconds for its answer.

    The model client has its own request timeout, so a late answer finishes
    quietly in the background; the caller has already moved on to a fallback
    and recorded the timeout.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # handed back to the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=target, name=f"stage-{label}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise StageTimeout(f"{label} did not answer within {timeout:g}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")
