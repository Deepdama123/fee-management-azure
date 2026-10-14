"""Fee calculations: the single definition of balance and payment status.

Rule (evaluated "as of" a date, so it is deterministic and testable):
    Paid            balance <= 0
    Overdue         balance  > 0  and  DueDate <  as_of   (due date has passed)
    Partially Paid  balance  > 0  and  DueDate >= as_of   (still within time)

The brief defines exactly these three statuses. Edge case, documented in
the README: a student who has paid nothing but is not yet due is reported
as "Partially Paid" (balance outstanding, not overdue).

STATUS_SQL holds the same rule as SQL predicates, so the database can
filter 5,000+ rows by status instead of loading them all into Python.
tests/test_fee_logic.py proves the Python and SQL versions always agree.
"""

from datetime import date
from decimal import Decimal

PAID = "Paid"
PARTIALLY_PAID = "Partially Paid"
OVERDUE = "Overdue"
STATUSES = (PAID, PARTIALLY_PAID, OVERDUE)

# Each predicate takes the as-of date as its single "?" parameter (or none).
STATUS_SQL = {
    PAID: ("s.PaidAmount >= s.TotalFee", 0),
    OVERDUE: ("s.PaidAmount < s.TotalFee AND s.DueDate < ?", 1),
    PARTIALLY_PAID: ("s.PaidAmount < s.TotalFee AND s.DueDate >= ?", 1),
}


def _to_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _to_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def balance(total_fee, paid_amount) -> Decimal:
    return max(_to_decimal(total_fee) - _to_decimal(paid_amount), Decimal("0"))


def payment_status(total_fee, paid_amount, due_date, as_of: date) -> str:
    if balance(total_fee, paid_amount) <= 0:
        return PAID
    if _to_date(due_date) < as_of:
        return OVERDUE
    return PARTIALLY_PAID


def days_overdue(total_fee, paid_amount, due_date, as_of: date) -> int:
    if payment_status(total_fee, paid_amount, due_date, as_of) != OVERDUE:
        return 0
    return (as_of - _to_date(due_date)).days


def fee_summary(row: dict, as_of: date) -> dict:
    """Adds the calculated fields to a student row from the database."""
    total, paid, due = row["totalFee"], row["paidAmount"], row["dueDate"]
    return {
        **row,
        "dueDate": _to_date(due).isoformat(),
        "balance": balance(total, paid),
        "status": payment_status(total, paid, due, as_of),
        "daysOverdue": days_overdue(total, paid, due, as_of),
        "asOf": as_of.isoformat(),
    }
