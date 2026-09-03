from datetime import date


LOAN_RULES = {
    "PERSONAL": {"min_amount": 1000, "max_amount": 50000, "rate": 8.9, "default_term": 36},
    "AUTO": {"min_amount": 5000, "max_amount": 80000, "rate": 6.4, "default_term": 60},
    "EDUCATION": {"min_amount": 1000, "max_amount": 60000, "rate": 4.5, "default_term": 48},
    "HOME": {"min_amount": 50000, "max_amount": 500000, "rate": 5.2, "default_term": 240},
    "BUSINESS": {"min_amount": 10000, "max_amount": 150000, "rate": 9.8, "default_term": 60},
}

LOAN_TYPE_ALIASES = {
    "PERSONAL LOAN": "PERSONAL",
    "AUTO LOAN": "AUTO",
    "CAR LOAN": "AUTO",
    "MORTGAGE": "HOME",
    "HOME LOAN": "HOME",
    "STUDENT LOAN": "EDUCATION",
    "EDUCATION LOAN": "EDUCATION",
    "BUSINESS LOAN": "BUSINESS",
}

MAX_DEBT_TO_INCOME = 0.40
LOAN_TYPES = sorted(LOAN_RULES.keys())


def normalize_loan_type(value):
    key = str(value or "").strip().upper()
    return LOAN_TYPE_ALIASES.get(key, key)


def add_months(base_date, months):
    month_index = base_date.month - 1 + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base_date.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def monthly_payment(principal, annual_rate_pct, months):
    if months <= 0:
        return float(principal)
    monthly_rate = (annual_rate_pct or 0) / 100 / 12
    if monthly_rate == 0:
        return principal / months
    return principal * monthly_rate / (1 - (1 + monthly_rate) ** (-months))


def evaluate_eligibility(data):
    loan_type = normalize_loan_type(data.get("loan_type"))
    rule = LOAN_RULES.get(loan_type)
    checks = []

    checks.append(
        {
            "check": "loan_type_supported",
            "passed": rule is not None,
            "detail": f"'{loan_type}' must be one of {', '.join(LOAN_TYPES)}"
            if rule is None
            else f"{loan_type} is a supported loan type",
        }
    )

    try:
        amount = float(data.get("requested_amount"))
        amount_valid = True
    except (TypeError, ValueError):
        amount = None
        amount_valid = False

    if rule is not None:
        in_range = amount_valid and rule["min_amount"] <= amount <= rule["max_amount"]
        checks.append(
            {
                "check": "amount_within_limits",
                "passed": in_range,
                "detail": (
                    f"Requested ${amount:,.2f} within allowed range "
                    f"${rule['min_amount']:,.2f}-${rule['max_amount']:,.2f}"
                    if in_range
                    else f"Requested amount must be between ${rule['min_amount']:,.2f} and ${rule['max_amount']:,.2f}"
                ),
            }
        )
    else:
        checks.append(
            {"check": "amount_within_limits", "passed": False, "detail": "No limits available for unknown loan type"}
        )

    purpose = str(data.get("loan_purpose", "") or "").strip()
    checks.append(
        {
            "check": "purpose_provided",
            "passed": bool(purpose),
            "detail": "Loan purpose stated" if purpose else "A loan purpose is required",
        }
    )

    term = data.get("term_months") or (rule["default_term"] if rule else None)
    estimated_payment = (
        round(monthly_payment(amount, rule["rate"] if rule else 10.0, int(term)), 2)
        if amount_valid and term
        else None
    )

    income_raw = data.get("monthly_income")
    try:
        income = float(income_raw) if income_raw not in (None, "") else None
    except (TypeError, ValueError):
        income = None

    if income and estimated_payment is not None:
        dti = estimated_payment / income
        affordable = dti <= MAX_DEBT_TO_INCOME
        checks.append(
            {
                "check": "affordability",
                "passed": affordable,
                "detail": (
                    f"Estimated monthly payment ${estimated_payment:,.2f} is "
                    f"{dti * 100:.1f}% of monthly income ${income:,.2f} "
                    f"(limit {MAX_DEBT_TO_INCOME * 100:.0f}%)"
                ),
            }
        )
    else:
        dti = None
        checks.append(
            {
                "check": "affordability",
                "passed": True,
                "detail": "Monthly income not provided; affordability check skipped"
                + (f"; estimated payment ${estimated_payment:,.2f}" if estimated_payment else ""),
            }
        )

    eligible = all(check["passed"] for check in checks)

    return {
        "eligible": eligible,
        "checks": checks,
        "loan_type": loan_type,
        "proposed_interest_rate": rule["rate"] if rule else None,
        "proposed_term_months": int(term) if term else None,
        "estimated_monthly_payment": estimated_payment,
        "debt_to_income_ratio": round(dti, 4) if dti is not None else None,
        "max_allowed_amount": rule["max_amount"] if rule else None,
    }


def build_schedule(principal, annual_rate_pct, months, start):
    schedule = []
    monthly_rate = annual_rate_pct / 100 / 12
    payment = monthly_payment(principal, annual_rate_pct, months)
    balance = float(principal)

    for number in range(1, months + 1):
        interest = balance * monthly_rate
        principal_part = payment - interest
        if number == months or principal_part > balance:
            principal_part = balance
            payment_final = principal_part + interest
        else:
            payment_final = payment
        due = add_months(start, number)
        schedule.append(
            {
                "due_date": due.isoformat(),
                "payment_amount": round(payment_final, 2),
                "principal_amount": round(principal_part, 2),
                "interest_amount": round(interest, 2),
                "amount_paid": 0,
                "payment_status": "UPCOMING",
            }
        )
        balance -= principal_part

    return schedule
