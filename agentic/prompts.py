"""Prompt file loader.

Prompt text lives in `prompts/<feature>/...` as plain `.txt`, never inline in
Python. Two reasons: teammates can edit their own prompts without touching
anyone's code, and a prompt change shows up as a reviewable diff.

Layout matches what the fraud backend already uses, so the loop and the
service read the same files:

    prompts/fraud-alerts/implementation/system_prompt.txt
    prompts/fraud-alerts/implementation/task_prompt.txt
    prompts/fraud-alerts/implementation/context_prompt.txt
    prompts/fraud-alerts/review/review_prompt.txt
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_ROOT = REPO_ROOT / "prompts"


class MissingPrompt(FileNotFoundError):
    """Raised with the repo-relative path, so the fix is obvious from the message."""


def load(family: str, relative_path: str) -> str:
    """Read `prompts/<family>/<relative_path>`.

    `family` is the feature folder (e.g. "fraud-alerts"), `relative_path` the
    file under it (e.g. "implementation/system_prompt.txt").
    """
    path = PROMPTS_ROOT / family / relative_path
    if not path.is_file():
        raise MissingPrompt(f"Missing prompt file: {path.relative_to(REPO_ROOT)}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise MissingPrompt(f"Prompt file is empty: {path.relative_to(REPO_ROOT)}")
    return text


def load_all(family: str, *relative_paths: str) -> list[str]:
    """Load several prompt files at once, in the order given."""
    return [load(family, rel) for rel in relative_paths]
