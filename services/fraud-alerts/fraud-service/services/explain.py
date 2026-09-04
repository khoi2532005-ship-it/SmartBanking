from services import account_context
from services.llm_client import create_chat_completion
from services.prompt_loader import load_prompt


def _build_evidence(alert, rule):
    account = account_context.fetch_account_context(alert.get("customer_id"))
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
        f"Account context: {account}" if account else "Account context: unavailable (Accounts service unreachable)",
    ]
    return "\n".join(lines)


def _looks_usable(explanation, rule, alert):
    if not explanation or not explanation.strip():
        return False
    text = explanation.lower()
    mentions_rule = (
        rule.get("rule_type", "").replace("_", " ") in text
        or rule.get("rule_name", "").lower() in text
    )
    try:
        mentions_amount = str(int(float(alert.get("transaction_amount", 0)))) in text
    except (TypeError, ValueError):
        mentions_amount = False
    return mentions_rule or mentions_amount


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


def generate_explanation(alert, rule):
    """Plan -> Act -> Observe -> Adapt for one alert.

    Plan: gather the evidence (rule + snapshotted transaction + account context).
    Act: call the LLM.
    Observe: check the explanation actually references the rule/amount, not generic filler.
    Adapt: retry once with a tightened prompt if Observe fails.

    Never raises - returns (explanation, degraded) so callers (detection's bulk
    run, or the on-demand /explain endpoint) can keep going instead of crashing
    when the LLM is unavailable (e.g. no API key configured).
    """
    evidence = _build_evidence(alert, rule)

    try:
        explanation = _ask(evidence)
    except Exception as exc:
        return f"AI explanation unavailable ({exc}).", True

    if _looks_usable(explanation, rule, alert):
        return explanation.strip(), False

    try:
        explanation = _ask(
            evidence,
            "\n\nYour previous answer did not clearly reference the triggered rule and the "
            "dollar amount. Be specific: name the rule and the amount.",
        )
    except Exception as exc:
        return f"AI explanation unavailable ({exc}).", True

    if _looks_usable(explanation, rule, alert):
        return explanation.strip(), False

    return explanation.strip() or "AI could not produce a reliable explanation for this alert.", True
