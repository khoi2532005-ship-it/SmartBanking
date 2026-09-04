from collections import defaultdict
from datetime import datetime, timedelta


def _parse_dt(value):
    return datetime.fromisoformat(str(value))


def _check_amount_over(transactions, rule):
    threshold = float(rule["threshold_value"])
    return [txn for txn in transactions if float(txn["amount"]) > threshold]


def _check_velocity(transactions, rule):
    """More than N transactions within M minutes, for the same customer."""
    n = int(rule["threshold_value"])
    window_minutes = int(rule.get("threshold_secondary") or 0)

    by_customer = defaultdict(list)
    for txn in transactions:
        by_customer[txn["customer_id"]].append(txn)

    hits = []
    for txns in by_customer.values():
        txns = sorted(txns, key=lambda t: _parse_dt(t["datetime_sent"]))
        for txn in txns:
            window_start = _parse_dt(txn["datetime_sent"])
            window_end = window_start + timedelta(minutes=window_minutes)
            in_window = [t for t in txns if window_start <= _parse_dt(t["datetime_sent"]) <= window_end]
            if len(in_window) > n:
                hits.append(max(in_window, key=lambda t: _parse_dt(t["datetime_sent"])))
                break  # one hit per customer per rule is enough to demonstrate detection
    return hits


def _check_unusual_time(transactions, rule):
    start_hour = int(rule["threshold_value"])
    end_hour = int(rule["threshold_secondary"]) if rule.get("threshold_secondary") is not None else 23
    return [txn for txn in transactions if start_hour <= _parse_dt(txn["datetime_sent"]).hour <= end_hour]


def _check_new_recipient_high_value(transactions, rule):
    """First-ever transfer to a recipient, above threshold. 'First-ever' is
    judged against the customer's full visible history (every transaction in
    the scanned set), not just a sub-window - per spec."""
    threshold = float(rule["threshold_value"])

    by_customer = defaultdict(list)
    for txn in transactions:
        by_customer[txn["customer_id"]].append(txn)

    hits = []
    for txns in by_customer.values():
        txns = sorted(txns, key=lambda t: _parse_dt(t["datetime_sent"]))
        seen_recipients = set()
        for txn in txns:
            recipient = txn.get("recipient_name")
            if not recipient:
                continue
            is_new = recipient not in seen_recipients
            seen_recipients.add(recipient)
            if is_new and float(txn["amount"]) > threshold:
                hits.append(txn)
    return hits


_EVALUATORS = {
    "amount_over": _check_amount_over,
    "velocity": _check_velocity,
    "unusual_time": _check_unusual_time,
    "new_recipient_high_value": _check_new_recipient_high_value,
}


def evaluate(transactions, rules):
    """Runs every enabled rule against the transaction set. Returns a list of
    (rule, transaction) hit pairs - one pair per rule that fired for that
    transaction (a single transaction can trip more than one rule)."""
    hits = []
    for rule in rules:
        if not rule.get("enabled"):
            continue
        evaluator = _EVALUATORS.get(rule["rule_type"])
        if evaluator is None:
            continue
        for txn in evaluator(transactions, rule):
            hits.append((rule, txn))
    return hits
