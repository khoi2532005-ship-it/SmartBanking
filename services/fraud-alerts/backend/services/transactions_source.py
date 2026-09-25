import os

import requests

from data.seed_transactions import TRANSACTIONS as SEED_TRANSACTIONS

TRANSACTIONS_SOURCE = os.getenv("TRANSACTIONS_SOURCE", "seed").strip().lower()
TRANSACTIONS_SERVICE_URL = os.getenv("TRANSACTIONS_SERVICE_URL", "http://localhost:5005")
ACCOUNTS_SERVICE_URL = os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:5001")
TIMEOUT = 5


class SourceUnavailable(Exception):
    """A service detection needs could not be read. Detection turns this into
    a 503 and writes nothing: scanning the seed fixture instead (as it used
    to) stored alerts for transactions that do not exist in Transactions."""


def _get_list(url, service):
    # One short sentence per failure - it is shown to the user as-is, and the
    # raw requests exception is several lines of connection-pool noise.
    try:
        response = requests.get(url, timeout=TIMEOUT)
    except requests.ConnectionError:
        raise SourceUnavailable(f"{service} unreachable at {url}") from None
    except requests.Timeout:
        raise SourceUnavailable(f"{service} did not answer within {TIMEOUT}s") from None
    except requests.RequestException as exc:
        raise SourceUnavailable(f"{service} request failed ({type(exc).__name__})") from None
    if response.status_code >= 400:
        raise SourceUnavailable(f"{service} answered HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise SourceUnavailable(f"{service} did not return JSON") from None
    if not isinstance(body, list):
        raise SourceUnavailable(f"{service} returned {type(body).__name__}, expected a list")
    return body


def _customer_by_account():
    """account_id -> customer_id, from the Accounts API. The Transactions API
    returns account_id only (it stopped joining accounts in b7c75fa), while
    alerts.customer_id is NOT NULL and the velocity and new-recipient rules
    group by customer."""
    accounts = _get_list(f"{ACCOUNTS_SERVICE_URL}/api/accounts", "Accounts service")
    return {
        str(account.get("account_id")): account.get("customer_id")
        for account in accounts
        if isinstance(account, dict)
    }


def _scannable(txn, customers):
    """The row ready for the rule engine, or None if it cannot be scanned:
    no customer can be resolved for it (its account is not in Accounts), or
    its amount is not a number. Amounts are signed - withdrawals are negative -
    and the threshold rules compare magnitude, so -7500 reads as 7500."""
    if not isinstance(txn, dict):
        return None

    customer_id = txn.get("customer_id")
    if customer_id is None:
        customer_id = customers.get(str(txn.get("account_id")))
    if customer_id is None:
        return None

    try:
        amount = abs(float(txn.get("amount")))
    except (TypeError, ValueError):
        return None

    return {**txn, "customer_id": customer_id, "amount": amount}


def fetch_transactions():
    """Returns (transactions, source, unscannable_count).

    TRANSACTIONS_SOURCE=seed scans the local sample fixture. =http scans the
    live Transactions API and raises SourceUnavailable when it - or Accounts,
    when customers have to be resolved - cannot be read."""
    if TRANSACTIONS_SOURCE != "http":
        return SEED_TRANSACTIONS, "seed", 0

    rows = _get_list(f"{TRANSACTIONS_SERVICE_URL}/api/transactions", "Transactions service")
    customers = {}
    if any(isinstance(row, dict) and row.get("customer_id") is None for row in rows):
        customers = _customer_by_account()

    scannable = [t for t in (_scannable(row, customers) for row in rows) if t is not None]
    return scannable, "http", len(rows) - len(scannable)
