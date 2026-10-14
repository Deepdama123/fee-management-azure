"""Test fixtures: the real repository and SQL against in-memory SQLite.

Only two things differ from Azure SQL: paging syntax (OFFSET/FETCH vs
LIMIT/OFFSET) and the table DDL. The seed mirrors sql/02_seed_data.sql
(same 20 students, due dates relative to "today").
"""

import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fees.config import Settings  # noqa: E402
from fees.repository import FeeRepository  # noqa: E402

sqlite3.register_adapter(Decimal, str)
sqlite3.register_adapter(date, date.isoformat)
sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" "))

TODAY = date(2026, 10, 14)

SCHEMA = """
CREATE TABLE dbo.Students (
    StudentID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL, Course TEXT NOT NULL,
    TotalFee NUMERIC NOT NULL CHECK (TotalFee >= 0),
    PaidAmount NUMERIC NOT NULL DEFAULT 0 CHECK (PaidAmount >= 0 AND PaidAmount <= TotalFee),
    DueDate TEXT NOT NULL, Email TEXT NOT NULL, UpdatedAt TEXT
);
CREATE TABLE dbo.Administrators (
    AdminID INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT NOT NULL,
    Role TEXT NOT NULL CHECK (Role IN ('FeeAdmin', 'FeeViewer')),
    Email TEXT NOT NULL UNIQUE, IsActive INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE dbo.FeeAudit (
    AuditID INTEGER PRIMARY KEY AUTOINCREMENT, StudentID INTEGER NOT NULL REFERENCES Students (StudentID),
    Action TEXT NOT NULL, OldTotalFee NUMERIC, NewTotalFee NUMERIC, OldPaidAmount NUMERIC,
    NewPaidAmount NUMERIC, OldDueDate TEXT, NewDueDate TEXT, ChangedBy TEXT NOT NULL, ChangedAt TEXT NOT NULL
);
"""

# (name, course, total, paid, due offset in days) - same as sql/02_seed_data.sql
SEED = [
    ("Aarav Sharma", "B.Tech CSE", 150000, 150000, -20),
    ("Diya Patel", "MBA", 220000, 220000, 15),
    ("Kabir Mehta", "B.Com", 60000, 60000, -60),
    ("Ananya Iyer", "M.Sc Data Science", 180000, 180000, 30),
    ("Vihaan Reddy", "BBA", 90000, 90000, -10),
    ("Isha Nair", "B.Tech CSE", 150000, 150000, 45),
    ("Arjun Singh", "MBA", 220000, 110000, 5),
    ("Saanvi Gupta", "B.Com", 60000, 30000, 12),
    ("Reyansh Joshi", "M.Sc Data Science", 180000, 90000, 20),
    ("Myra Kulkarni", "BBA", 90000, 45000, 25),
    ("Aditya Rao", "B.Tech CSE", 150000, 100000, 10),
    ("Kiara Desai", "MBA", 220000, 50000, 40),
    ("Rohan Bhatt", "B.Com", 60000, 10000, 1),
    ("Neha Verma", "BBA", 90000, 60000, -3),
    ("Siddharth Menon", "M.Sc Data Science", 180000, 0, -7),
    ("Pooja Shah", "B.Tech CSE", 150000, 75000, -15),
    ("Rahul Kapoor", "MBA", 220000, 200000, -21),
    ("Tanvi Pillai", "B.Com", 60000, 0, -30),
    ("Yash Malhotra", "BBA", 90000, 20000, -45),
    ("Meera Chopra", "M.Sc Data Science", 180000, 120000, -1),
]

ADMIN = "deep@contoso.onmicrosoft.com"
VIEWER = "viewer@contoso.onmicrosoft.com"
FORMER = "former@contoso.onmicrosoft.com"


class SqliteDatabase:
    driver = sqlite3

    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("ATTACH DATABASE ':memory:' AS dbo")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        # StudentIDs start at 1001, as in Azure SQL
        self.connection.execute("INSERT INTO dbo.sqlite_sequence (name, seq) VALUES ('Students', 1000)")

    @contextmanager
    def transaction(self):
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise


class SqliteFeeRepository(FeeRepository):
    def _page(self, order_by, offset, size):
        return f"ORDER BY {order_by} LIMIT ? OFFSET ?", (size, offset)


def seed(connection, today=TODAY):
    for i, (name, course, total, paid, offset) in enumerate(SEED, start=1):
        connection.execute(
            "INSERT INTO dbo.Students (Name, Course, TotalFee, PaidAmount, DueDate, Email) VALUES (?,?,?,?,?,?)",
            (name, course, total, paid, (today + timedelta(days=offset)).isoformat(), f"inbox+s{i}@example.com"))
    connection.executemany(
        "INSERT INTO dbo.Administrators (Name, Role, Email, IsActive) VALUES (?,?,?,?)",
        [("Deep", "FeeAdmin", ADMIN, 1), ("Viewer", "FeeViewer", VIEWER, 1), ("Former", "FeeAdmin", FORMER, 0)])
    connection.commit()


class FixedSettings(Settings):
    def today(self):
        return TODAY


def make_settings(mode="local-dev"):
    return FixedSettings("unused", mode, "11111111-2222-3333-4444-555555555555",
                         ("api://fee-api", "00000000-aaaa-bbbb-cccc-000000000000"), "Asia/Kolkata")


class FakeServices:
    def __init__(self, repository, settings=None):
        self._repository = repository
        self.settings = settings or make_settings()

    def repository(self):
        return self._repository


@pytest.fixture
def repo():
    db = SqliteDatabase()
    seed(db.connection)
    return SqliteFeeRepository(db)


@pytest.fixture
def services(repo):
    return FakeServices(repo)
