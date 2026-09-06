"""Mode registry - the one file the whole team edits.

Adding your feature is one import and one entry in MODES. Move your feature
out of PENDING at the same time and the menu picks it up automatically.

Keeping the not-yet-built features listed in PENDING (rather than shipping four
copies of the template) means the menu shows the full five-feature shape from
day one without carrying dead code that nobody runs.
"""

from __future__ import annotations

from agentic.core import Mode
from agentic.modes.fraud import FraudMode

# Implemented modes, in menu order.
MODES: dict[str, Mode] = {
    mode.key: mode
    for mode in (
        FraudMode(),
    )
}

# Not built yet. Copy agentic/modes/_template.py, implement the four methods,
# import it above, add it to MODES, and delete the line here.
PENDING: dict[str, tuple[str, str]] = {
    "accounts": ("Accounts & Customers", "William"),
    "transactions": ("Transactions", "Aidan"),
    "budgeting": ("Budgeting & Insights", "Bao"),
    "loans": ("Loans & Credit", "David"),
}


def all_keys() -> list[str]:
    return list(MODES) + list(PENDING)
