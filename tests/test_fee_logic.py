"""The fee rule, and proof that the Python and SQL versions agree."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from conftest import TODAY
from fees.fee_logic import (OVERDUE, PAID, PARTIALLY_PAID, STATUSES, balance, days_overdue,
                            payment_status)


@pytest.mark.parametrize("total, paid, due_offset, expected", [
    (1000, 1000, -5, PAID),              # paid in full, even if late
    (1000, 1000, 5, PAID),
    (1000, 400, 5, PARTIALLY_PAID),      # balance, still within time
    (1000, 400, 0, PARTIALLY_PAID),      # due TODAY is not yet overdue
    (1000, 400, -1, OVERDUE),            # one day late
    (1000, 0, -10, OVERDUE),
    (1000, 0, 10, PARTIALLY_PAID),       # documented edge case
    (0, 0, -10, PAID),                   # nothing owed
])
def test_payment_status(total, paid, due_offset, expected):
    assert payment_status(total, paid, TODAY + timedelta(days=due_offset), TODAY) == expected


def test_balance_and_days_overdue():
    assert balance(Decimal("1000.50"), Decimal("200.25")) == Decimal("800.25")
    assert days_overdue(1000, 0, TODAY - timedelta(days=7), TODAY) == 7
    assert days_overdue(1000, 1000, TODAY - timedelta(days=7), TODAY) == 0
    assert days_overdue(1000, 0, "2026-10-01", date(2026, 10, 14)) == 13


def test_seed_has_the_intended_mix(repo):
    rows, total = repo.list_students(TODAY, None, None, 1, 100)
    statuses = [payment_status(r["totalFee"], r["paidAmount"], r["dueDate"], TODAY) for r in rows]
    assert total == 20
    assert statuses.count(PAID) == 6
    assert statuses.count(PARTIALLY_PAID) == 7
    assert statuses.count(OVERDUE) == 7


@pytest.mark.parametrize("as_of_offset", [-60, -1, 0, 1, 30, 90])
def test_sql_filter_agrees_with_python_rule(repo, as_of_offset):
    """Whatever date we evaluate on, filtering in SQL gives exactly the rows
    the Python rule would label with that status."""
    as_of = TODAY + timedelta(days=as_of_offset)
    everyone, _ = repo.list_students(as_of, None, None, 1, 100)
    for status in STATUSES:
        from_sql, count = repo.list_students(as_of, status, None, 1, 100)
        expected = {r["studentId"] for r in everyone
                    if payment_status(r["totalFee"], r["paidAmount"], r["dueDate"], as_of) == status}
        assert {r["studentId"] for r in from_sql} == expected, status
        assert count == len(expected)
