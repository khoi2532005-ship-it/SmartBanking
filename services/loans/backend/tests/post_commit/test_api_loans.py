import os
import requests


LOANS_DB_URL = os.getenv("LOANS_DB_URL", "http://localhost:5002")
TIMEOUT = 5


def test_service_health():
    response = requests.get(f"{LOANS_DB_URL}/api/health", timeout=TIMEOUT)
    assert response.status_code == 200
    assert response.json()["service"] == "loan-service"


def test_loans_exist():
    response = requests.get(f"{LOANS_DB_URL}/api/loans", timeout=TIMEOUT)
    assert response.status_code == 200
    loans = response.json()
    assert loans
    assert all({"loan_id", "customer_id", "loan_type", "status"} <= set(loan) for loan in loans)


def test_loan_by_id():
    loans = requests.get(f"{LOANS_DB_URL}/api/loans", timeout=TIMEOUT).json()
    assert loans, "no loans available to check"

    loan_id = loans[0]["loan_id"]
    response = requests.get(f"{LOANS_DB_URL}/api/loans/{loan_id}", timeout=TIMEOUT)
    assert response.status_code == 200
    assert response.json()["loan_id"] == loan_id


def test_loan_eligibility():
    loans = requests.get(f"{LOANS_DB_URL}/api/loans", timeout=TIMEOUT).json()
    assert loans, "no loans available to check"

    loan_id = loans[0]["loan_id"]
    response = requests.get(
        f"{LOANS_DB_URL}/api/loans/{loan_id}/eligibility", timeout=TIMEOUT
    )
    assert response.status_code == 200
    result = response.json()
    assert result["loan_id"] == loan_id
    assert {"eligible", "checks"} <= set(result["eligibility"])


def test_repayments_exist():
    response = requests.get(f"{LOANS_DB_URL}/api/repayments", timeout=TIMEOUT)
    assert response.status_code == 200
    repayments = response.json()
    assert repayments
    assert all({"repayment_id", "loan_id", "due_date"} <= set(row) for row in repayments)


def test_repayment_by_id():
    repayments = requests.get(f"{LOANS_DB_URL}/api/repayments", timeout=TIMEOUT).json()
    assert repayments, "no repayments available to check"

    repayment_id = repayments[0]["repayment_id"]
    response = requests.get(
        f"{LOANS_DB_URL}/api/repayments/{repayment_id}", timeout=TIMEOUT
    )
    assert response.status_code == 200
    assert response.json()["repayment_id"] == repayment_id


def test_upcoming_repayments():
    response = requests.get(
        f"{LOANS_DB_URL}/api/repayments/upcoming", timeout=TIMEOUT
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)