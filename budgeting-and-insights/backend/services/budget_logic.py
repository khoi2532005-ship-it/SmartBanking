"""Budget-versus-actual calculations.

Pure functions: no HTTP, no database access, so they are easy to reason about
and to unit test.
"""

OVER_BUDGET = "OVER_BUDGET"
NEAR_LIMIT = "NEAR_LIMIT"
ON_TRACK = "ON_TRACK"

NEAR_LIMIT_THRESHOLD = 80.0


def evaluate_budget(budget, spent):
    """Compare one budget against actual spend."""
    limit = float(budget["monthly_limit"])
    spent = round(float(spent or 0.0), 2)
    remaining = round(limit - spent, 2)

    percent_used = round(spent / limit * 100, 1) if limit > 0 else 0.0

    if limit > 0 and spent > limit:
        status = OVER_BUDGET
    elif percent_used >= NEAR_LIMIT_THRESHOLD:
        status = NEAR_LIMIT
    else:
        status = ON_TRACK

    return {
        "budget_id": budget["budget_id"],
        "customer_id": budget["customer_id"],
        "category": budget["category"],
        "month": budget["month"],
        "year": budget["year"],
        "monthly_limit": round(limit, 2),
        "spent": spent,
        "remaining": remaining,
        "percent_used": percent_used,
        "status": status,
        "over_budget": status == OVER_BUDGET,
        "over_by": round(spent - limit, 2) if spent > limit else 0.0,
    }


def build_summary(budgets, spend_totals):
    """Evaluate every budget and roll the results up into one summary."""
    lines = [
        evaluate_budget(budget, spend_totals.get(budget["category"], 0.0))
        for budget in budgets
    ]

    total_limit = round(sum(line["monthly_limit"] for line in lines), 2)
    total_spent = round(sum(line["spent"] for line in lines), 2)
    over = [line for line in lines if line["over_budget"]]

    # Spending in categories the customer has not budgeted for at all.
    budgeted = {budget["category"] for budget in budgets}
    unbudgeted = [
        {"category": category, "spent": amount}
        for category, amount in sorted(spend_totals.items())
        if category not in budgeted and amount > 0
    ]

    return {
        "budgets": lines,
        "totals": {
            "total_limit": total_limit,
            "total_spent": total_spent,
            "total_remaining": round(total_limit - total_spent, 2),
            "percent_used": round(total_spent / total_limit * 100, 1)
            if total_limit > 0
            else 0.0,
            "budget_count": len(lines),
            "over_budget_count": len(over),
        },
        "over_budget_categories": [line["category"] for line in over],
        "unbudgeted_spending": unbudgeted,
    }
