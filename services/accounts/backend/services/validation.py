"""Request validation for the Multi-Agent routes (Release 2).

Pure functions, so the rules they enforce can be unit-tested without a
running database service or the Multi-Agent Server. Each raises
ValidationError with a message that is safe to show a person; the routes
turn it into a 400.
"""

import re

WORKFLOW_ID = re.compile(r"wf_[0-9a-f]{8}")
MAX_TASK_LENGTH = 1000
MAX_NOTE_LENGTH = 1000
MAX_REVIEWER_LENGTH = 60
WORKFLOW_DECISIONS = ("accept", "partially_accept", "reject")


class ValidationError(ValueError):
    """The body is valid JSON but one of its values is not acceptable."""


def positive_int(value, field):
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a positive integer")
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a positive integer") from None
    if result < 1:
        raise ValidationError(f"{field} must be a positive integer")
    return result


def choice(value, field, allowed):
    result = str(value if value is not None else "").strip().lower()
    if result not in allowed:
        raise ValidationError(f"{field} must be one of {', '.join(allowed)}")
    return result


def workflow_id(value):
    """A Multi-Agent workflow id: the only thing this service puts in a server URL.
    fullmatch, because "$" would also accept a trailing newline."""
    text = value if isinstance(value, str) else ""
    if not WORKFLOW_ID.fullmatch(text):
        raise ValidationError("workflow id must look like wf_1a2b3c4d")
    return text


def validate_workflow_start(data):
    """(task, customer_id) for a new workflow. Every workflow is about one customer."""
    task = data.get("task")
    task = task.strip() if isinstance(task, str) else ""
    if not task:
        raise ValidationError("task is required")
    if len(task) > MAX_TASK_LENGTH:
        raise ValidationError(f"task must be {MAX_TASK_LENGTH} characters or fewer")
    return task, positive_int(data.get("customer_id"), "customer_id")


def _optional_text(data, field, limit):
    value = data.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    value = value.strip()
    if len(value) > limit:
        raise ValidationError(f"{field} must be {limit} characters or fewer")
    return value


def validate_review(data):
    """(decision, note, reviewer) for the reviewer's decision. Partially accept
    releases the answer with a correction attached, so it needs the correction."""
    decision = choice(data.get("decision"), "decision", WORKFLOW_DECISIONS)
    note = _optional_text(data, "note", MAX_NOTE_LENGTH)
    reviewer = _optional_text(data, "reviewer", MAX_REVIEWER_LENGTH)
    if decision == "partially_accept" and not note:
        raise ValidationError("partially_accept needs a note saying what to correct")
    return decision, note, reviewer
