"""Request validation for the rules and alerts routes.

Pure functions, so the rules they enforce can be unit-tested without a running
database service. Each raises ValidationError with a message that is safe to
show a person; the routes turn it into a 400.
"""

import math
from datetime import datetime

from services.constants import ALERT_STATUSES, RULE_TYPES, SEVERITIES

RULE_FIELDS = ("rule_name", "rule_type", "threshold_value", "threshold_secondary", "severity", "enabled")
MAX_RULE_NAME_LENGTH = 100


class ValidationError(ValueError):
    """The body is valid JSON but one of its values is not acceptable."""


def number(value, field):
    """A finite float. Numeric strings are accepted (the frontend's form sends
    "5000"), but booleans, NaN and infinity are not: float() takes all three,
    and each one silently breaks a threshold comparison."""
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{field} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number") from None
    if not math.isfinite(result):
        raise ValidationError(f"{field} must be a finite number")
    return result


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


def enabled_flag(value):
    """0 or 1. Strings only as "true"/"false"/"1"/"0": any other non-empty
    string is truthy, which is how "false" used to be stored as enabled."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
        return 1 if value.strip().lower() in ("true", "1") else 0
    raise ValidationError("enabled must be true/false or 1/0")


def iso_datetime(value, field):
    text = str(value).strip()
    try:
        datetime.fromisoformat(text)
    except ValueError:
        raise ValidationError(f"{field} must be an ISO date, e.g. 2026-09-01 or 2026-09-01T14:30:00") from None
    return text


def validate_rule(changes, existing=None):
    """The complete, cleaned rule to store, or ValidationError.

    For an update, `existing` is the stored rule and `changes` the new values.
    The merged rule is validated as a whole, so switching a rule to velocity
    without giving it a window is caught as well.
    """
    rule = {**(existing or {}), **changes}

    name = rule.get("rule_name")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("rule_name is required")
    name = name.strip()
    if len(name) > MAX_RULE_NAME_LENGTH:
        raise ValidationError(f"rule_name must be {MAX_RULE_NAME_LENGTH} characters or fewer")

    rule_type = choice(rule.get("rule_type"), "rule_type", RULE_TYPES)
    severity = choice(rule.get("severity"), "severity", SEVERITIES)
    value = number(rule.get("threshold_value"), "threshold_value")
    secondary = rule.get("threshold_secondary")
    secondary = None if secondary in (None, "") else number(secondary, "threshold_secondary")

    if rule_type == "velocity":
        # value = N transactions, secondary = M minutes
        if value < 1 or not value.is_integer():
            raise ValidationError("velocity threshold_value is a transaction count: a whole number, 1 or more")
        if secondary is None or secondary < 1 or not secondary.is_integer():
            raise ValidationError("velocity needs threshold_secondary: the window in whole minutes, 1 or more")
        value, secondary = int(value), int(secondary)
    elif rule_type == "unusual_time":
        # value = start hour, secondary = end hour (exclusive, may wrap past midnight)
        for hour, field in ((value, "threshold_value"), (secondary, "threshold_secondary")):
            if hour is None or not hour.is_integer() or not 0 <= hour <= 23:
                raise ValidationError(f"unusual_time needs {field} as a whole hour from 0 to 23")
        if value == secondary:
            raise ValidationError("unusual_time start and end hours must differ")
        value, secondary = int(value), int(secondary)
    else:
        # amount_over / new_recipient_high_value: value = amount, no secondary
        if value < 0:
            raise ValidationError("threshold_value must be 0 or more")
        secondary = None

    return {
        "rule_name": name,
        "rule_type": rule_type,
        "threshold_value": value,
        "threshold_secondary": secondary,
        "severity": severity,
        "enabled": enabled_flag(rule.get("enabled", 1)),
    }


def validate_new_alert(data):
    """The cleaned alert to create, or ValidationError. The IDs must be real
    integers: they are logical foreign keys into Accounts and Transactions,
    and a string here used to be stored as-is and rendered raw."""
    payload = {
        "rule_id": positive_int(data.get("rule_id"), "rule_id"),
        "customer_id": positive_int(data.get("customer_id"), "customer_id"),
        "transaction_id": positive_int(data.get("transaction_id"), "transaction_id"),
        "transaction_amount": number(data.get("transaction_amount"), "transaction_amount"),
        "severity": choice(data.get("severity"), "severity", SEVERITIES),
        "status": choice(data.get("status", "new"), "status", ALERT_STATUSES),
    }
    if payload["transaction_amount"] < 0:
        raise ValidationError("transaction_amount must be 0 or more")
    for field in ("transaction_recipient", "transaction_category"):
        value = data.get(field)
        payload[field] = None if value is None else str(value)
    when = data.get("transaction_datetime")
    payload["transaction_datetime"] = None if when in (None, "") else iso_datetime(when, "transaction_datetime")
    return payload


def validate_alert_filters(args):
    """GET /api/alerts query parameters. A value that cannot match used to
    reach SQLite as text and quietly return nothing (min_amount=abc) or
    everything (max_amount=abc)."""
    filters = {}
    if args.get("status"):
        filters["status"] = choice(args["status"], "status", ALERT_STATUSES)
    for field in ("rule_id", "customer_id"):
        if args.get(field):
            filters[field] = positive_int(args[field], field)
    for field in ("min_amount", "max_amount"):
        if args.get(field):
            filters[field] = number(args[field], field)
    for field in ("date_from", "date_to"):
        if args.get(field):
            filters[field] = iso_datetime(args[field], field)
    if args.get("q"):
        filters["q"] = args["q"]
    return filters
