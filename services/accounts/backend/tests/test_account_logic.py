"""Unit checks for the Accounts & Customers deterministic business rules.

These cover services/account_logic.py directly - no Flask, no SQLite, no
network, no LLM. They exist so the "evidence" evaluate_risk() hands to the
AI layer can be verified on its own, the same way the budgeting feature's
test_budget_logic.py verifies its budget-versus-actual maths.

Run with:  python -m tests.test_account_logic   (from services/accounts/backend/)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.account_logic import evaluate_risk, summarize_accounts  # noqa: E402


def _account(account_id, status="ACTIVE", balance=0.0):
    return {"account_id": account_id, "status": status, "balance": balance}


class TestSummarizeAccounts(unittest.TestCase):
    def test_counts_by_status(self):
        accounts = [
            _account(1, "ACTIVE", 100),
            _account(2, "ACTIVE", 200),
            _account(3, "INACTIVE", 0),
            _account(4, "CLOSED", 0),
        ]
        totals = summarize_accounts(accounts)
        self.assertEqual(totals["account_count"], 4)
        self.assertEqual(totals["active_count"], 2)
        self.assertEqual(totals["inactive_count"], 1)
        self.assertEqual(totals["closed_count"], 1)

    def test_total_balance_only_counts_active_accounts(self):
        accounts = [_account(1, "ACTIVE", 100.50), _account(2, "CLOSED", 9000)]
        totals = summarize_accounts(accounts)
        self.assertEqual(totals["total_balance"], 100.50)

    def test_negative_balance_detection(self):
        accounts = [_account(1, "ACTIVE", -50.25), _account(2, "ACTIVE", 500)]
        totals = summarize_accounts(accounts)
        self.assertTrue(totals["has_negative_balance"])
        self.assertEqual(totals["negative_balance_accounts"], [1])

    def test_no_accounts_is_not_an_error(self):
        totals = summarize_accounts([])
        self.assertEqual(totals["account_count"], 0)
        self.assertFalse(totals["has_negative_balance"])


class TestEvaluateRisk(unittest.TestCase):
    def test_low_risk_when_everything_healthy(self):
        customer = {"email": "a@example.com", "phone": "0400000000"}
        accounts = [_account(1, "ACTIVE", 8250.40), _account(2, "ACTIVE", 1120.15)]
        result = evaluate_risk(customer, accounts)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertTrue(all(c["passed"] for c in result["checks"]))

    def test_high_risk_when_no_active_accounts(self):
        customer = {"email": "a@example.com", "phone": "0400000000"}
        accounts = [_account(1, "CLOSED", 0)]
        result = evaluate_risk(customer, accounts)
        self.assertEqual(result["risk_level"], "HIGH")

    def test_high_risk_when_overdrawn(self):
        customer = {"email": "a@example.com", "phone": "0400000000"}
        accounts = [_account(1, "ACTIVE", -10.0)]
        result = evaluate_risk(customer, accounts)
        self.assertEqual(result["risk_level"], "HIGH")

    def test_missing_contact_details_is_flagged(self):
        customer = {"email": None, "phone": None}
        accounts = [_account(1, "ACTIVE", 5000)]
        result = evaluate_risk(customer, accounts)
        contact_check = next(c for c in result["checks"] if c["check"] == "contact_details_complete")
        self.assertFalse(contact_check["passed"])

    def test_medium_risk_for_low_balance_active_customer(self):
        customer = {"email": "a@example.com", "phone": "0400000000"}
        accounts = [_account(1, "ACTIVE", 25.0)]
        result = evaluate_risk(customer, accounts)
        self.assertEqual(result["risk_level"], "MEDIUM")

    def test_risk_level_is_always_one_of_the_three_bands(self):
        customer = {"email": "a@example.com", "phone": "0400000000"}
        for balance in (-100, 0, 50, 500, 5000):
            result = evaluate_risk(customer, [_account(1, "ACTIVE", balance)])
            self.assertIn(result["risk_level"], ("LOW", "MEDIUM", "HIGH"))


if __name__ == "__main__":
    unittest.main()
