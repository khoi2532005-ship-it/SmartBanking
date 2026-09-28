import logging

from services import account_context, mcp_client
from services.llm_client import create_chat_completion, describe_error
from services.local_servers import BadServerResponse, ServerDisabled, ServerUnavailable
from services.prompt_loader import load_prompt

logger = logging.getLogger("fraud.explain")

# Alert history is optional context: an explanation should not wait long for it.
HISTORY_READ_TIMEOUT = 5
HISTORY_FIELDS = ("alert_count", "by_severity", "by_status")


def fetch_alert_history(customer_id):
    """The customer's alert counts from the shared MCP server's
    fraud_alerts_count tool, as (counts, problem).

    The same tool result the AI Mode tab shows, reused as LLM context. It is
    counts only (no amounts, recipients or transaction ids), so it is safe to
    put in a prompt. counts is None when MCP could not provide it, problem
    says why, and the explanation goes ahead without it."""
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return None, "the alert has no usable customer id"
    try:
        _, result = mcp_client.fraud_alerts_count(customer_id=customer_id, read_timeout=HISTORY_READ_TIMEOUT)
    except (ServerDisabled, ServerUnavailable, BadServerResponse, mcp_client.ToolFailed) as exc:
        logger.info("Plan: no alert history for customer %s - %s", customer_id, exc)
        return None, str(exc)
    counts = {field: result.get(field) for field in HISTORY_FIELDS}
    logger.info("Plan: alert history for customer %s via MCP %s: %s alert(s)",
                customer_id, mcp_client.FRAUD_TOOL, counts["alert_count"])
    return counts, None


def _history_line(history):
    counts, _problem = history
    if counts is None:
        # The reason (an internal URL, a start command) is for the page and the
        # log, not the LLM.
        return "Alert history: unavailable"

    def spread(groups):
        return ", ".join(f"{name} {count}" for name, count in sorted((groups or {}).items())) or "none"

    return (f"Alert history (MCP tool {mcp_client.FRAUD_TOOL}, includes this alert): "
            f"{counts['alert_count']} alert(s) for this customer; "
            f"by severity: {spread(counts['by_severity'])}; by status: {spread(counts['by_status'])}")


def _build_evidence(alert, rule, history=None):
    account, problem = account_context.fetch_account_context(alert.get("customer_id"))
    lines = [
        f"Alert ID: {alert.get('alert_id')}",
        f"Rule triggered: {rule.get('rule_name')} ({rule.get('rule_type')})",
        f"Threshold: {rule.get('threshold_value')}"
        + (f" / {rule.get('threshold_secondary')}" if rule.get("threshold_secondary") is not None else ""),
        f"Transaction amount: ${alert.get('transaction_amount')}",
        f"Recipient: {alert.get('transaction_recipient')}",
        f"Date/time: {alert.get('transaction_datetime')}",
        f"Category: {alert.get('transaction_category')}",
        f"Severity: {alert.get('severity')}",
        f"Account context: {account}" if account else f"Account context: unavailable ({problem})",
    ]
    if history is not None:
        lines.append(_history_line(history))
    return "\n".join(lines)


def _looks_usable(explanation, rule, alert):
    if not explanation or not explanation.strip():
        return False
    text = explanation.lower()
    rule_type = (rule.get("rule_type") or "").replace("_", " ")
    rule_name = (rule.get("rule_name") or "").lower()
    # Both are checked for emptiness: "" is "in" every string, which made an
    # alert from an unnamed rule pass Observe with any text at all.
    mentions_rule = (rule_type and rule_type in text) or (rule_name and rule_name in text)
    try:
        amount = int(float(alert.get("transaction_amount", 0)))
        # the model usually writes $7,500 rather than 7500
        mentions_amount = str(amount) in text or f"{amount:,}" in text
    except (TypeError, ValueError):
        mentions_amount = False
    return bool(mentions_rule or mentions_amount)


def _ask(evidence, extra_instruction=""):
    system_prompt = load_prompt("implementation/system_prompt.txt")
    context_prompt = load_prompt("implementation/context_prompt.txt")
    task_prompt = load_prompt("implementation/task_prompt.txt")

    return create_chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"{context_prompt}\n\n{task_prompt}{extra_instruction}\n\nEvidence:\n{evidence}",
            },
        ],
        # Newer Gemini models spend part of this budget on hidden reasoning
        # before the visible answer - 300 was cutting real answers off
        # mid-sentence in testing even though the call itself succeeded.
        max_tokens=1000,
        temperature=0.2,
    )


def generate_explanation(alert, rule, history=None):
    """Plan -> Act -> Observe -> Adapt for one alert.

    Plan: gather the evidence (rule + snapshotted transaction + account context,
    plus the MCP alert history when the caller passes fetch_alert_history()).
    Act: call the LLM.
    Observe: check the explanation actually references the rule/amount, not generic filler.
    Adapt: retry once with a tightened prompt if Observe fails.

    Never raises - returns (explanation, degraded) so callers (detection's bulk
    run, or the on-demand /explain endpoint) can keep going instead of crashing
    when the LLM is unavailable (e.g. no API key configured). Only the on-demand
    endpoint passes history, so a bulk run makes no MCP call per alert.
    """
    evidence = _build_evidence(alert, rule, history)

    try:
        explanation = _ask(evidence)
    except Exception as exc:
        logger.warning("Act: LLM call for alert %s failed: %s", alert.get("alert_id"), exc)
        return f"AI explanation unavailable: {describe_error(exc)}", True

    if _looks_usable(explanation, rule, alert):
        return explanation.strip(), False

    logger.info("Observe: explanation for alert %s names neither the rule nor the amount - "
                "Adapt: retrying once with a tightened prompt", alert.get("alert_id"))
    try:
        explanation = _ask(
            evidence,
            "\n\nYour previous answer did not clearly reference the triggered rule and the "
            "dollar amount. Be specific: name the rule and the amount.",
        )
    except Exception as exc:
        logger.warning("Adapt: retry for alert %s failed: %s", alert.get("alert_id"), exc)
        return f"AI explanation unavailable: {describe_error(exc)}", True

    if _looks_usable(explanation, rule, alert):
        return explanation.strip(), False

    return explanation.strip() or "AI could not produce a reliable explanation for this alert.", True
