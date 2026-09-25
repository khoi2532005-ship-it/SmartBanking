from collections import defaultdict
from datetime import date, datetime, timedelta, timezone


def _timestamp(value):
    """(datetime, has_time) for an ISO string, or (None, False) when it is
    missing or unparseable - one malformed row from the Transactions API must
    not crash the whole scan.

    has_time is False for a bare date such as "2026-09-01" (what the live
    Transactions API stores). It parses as midnight, but carries no time of
    day at all, so time-based rules must skip it rather than read it as 00:00.
    """
    text = str(value).strip() if value is not None else ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, False
    try:
        date.fromisoformat(text)
    except ValueError:
        return parsed, True
    return parsed, False


def _sort_key(ts):
    """Offset-aware and naive timestamps cannot be compared; an aware one is
    brought to naive UTC so a mixed batch still sorts."""
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts


def _check_amount_over(transactions, rule):
    threshold = float(rule["threshold_value"])
    return [txn for txn in transactions if float(txn["amount"]) > threshold]


def _check_velocity(transactions, rule):
    """More than N transactions within M minutes, for the same customer.
    Rows without a time of day are left out: a minutes-wide window cannot
    be placed on a bare date."""
    n = int(rule["threshold_value"])
    window = timedelta(minutes=int(rule.get("threshold_secondary") or 0))

    by_customer = defaultdict(list)
    for txn in transactions:
        ts, has_time = _timestamp(txn.get("date"))
        if has_time:
            by_customer[txn["customer_id"]].append((_sort_key(ts), txn))

    hits = []
    for rows in by_customer.values():
        rows.sort(key=lambda row: row[0])
        for window_start, _ in rows:
            in_window = [txn for ts, txn in rows if window_start <= ts <= window_start + window]
            if len(in_window) > n:
                hits.append(in_window[-1])
                break  # one hit per customer per rule is enough to demonstrate detection
    return hits


def _check_unusual_time(transactions, rule):
    """Transaction time in [start hour, end hour): the end hour is exclusive,
    so 0-5 covers 00:00-04:59. A start after the end wraps past midnight:
    22-4 covers 22:00-03:59."""
    start = int(rule["threshold_value"])
    end = int(rule["threshold_secondary"]) if rule.get("threshold_secondary") is not None else 24
    if start == end:
        return []  # an empty window; the API no longer accepts one

    hits = []
    for txn in transactions:
        ts, has_time = _timestamp(txn.get("date"))
        if not has_time:
            continue
        inside = start <= ts.hour < end if start < end else (ts.hour >= start or ts.hour < end)
        if inside:
            hits.append(txn)
    return hits


def _check_new_recipient_high_value(transactions, rule):
    """First-ever transfer to a recipient, above threshold. 'First-ever' is
    judged against the customer's full visible history (every transaction in
    the scanned set), not just a sub-window - per spec."""
    threshold = float(rule["threshold_value"])

    by_customer = defaultdict(list)
    for txn in transactions:
        ts, _ = _timestamp(txn.get("date"))
        if ts is not None:
            by_customer[txn["customer_id"]].append((_sort_key(ts), txn))

    hits = []
    for rows in by_customer.values():
        # transaction_id breaks ties between rows that only carry a date
        rows.sort(key=lambda row: (row[0], row[1].get("transaction_id") or 0))
        seen_recipients = set()
        for _, txn in rows:
            recipient = txn.get("description")
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


def _is_enabled(rule):
    # A stored "false" is a truthy string; only 1/true count as enabled.
    return str(rule.get("enabled")).strip().lower() in ("1", "true")


def evaluate(transactions, rules, skipped_rules=None):
    """Runs every enabled rule against the transaction set. Returns a list of
    (rule, transaction) hit pairs - one pair per rule that fired for that
    transaction (a single transaction can trip more than one rule).

    A rule whose stored thresholds cannot be used (a non-numeric value saved
    before the API validated them) is skipped rather than failing the whole
    scan; its rule_id is appended to skipped_rules when a list is given."""
    hits = []
    for rule in rules:
        if not _is_enabled(rule):
            continue
        evaluator = _EVALUATORS.get(rule["rule_type"])
        if evaluator is None:
            continue
        try:
            fired = evaluator(transactions, rule)
        except (TypeError, ValueError, KeyError):
            if skipped_rules is not None:
                skipped_rules.append(rule["rule_id"])
            continue
        hits.extend((rule, txn) for txn in fired)
    return hits
