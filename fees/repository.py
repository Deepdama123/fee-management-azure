"""Data access: the only module that runs SQL."""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from . import queries
from .errors import ConflictError, NotFoundError, ServiceUnavailableError
from .fee_logic import OVERDUE, STATUS_SQL
from .validation import UPDATABLE_FEE_FIELDS

logger = logging.getLogger(__name__)


def _camel(column: str) -> str:
    name = column[0].lower() + column[1:]
    return name[:-2] + "Id" if name.endswith("ID") else name


def _rows(cursor) -> list[dict]:
    columns = [_camel(c[0]) for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class FeeRepository:
    def __init__(self, database):
        self._db = database

    # SQL Server paging. Overridden for SQLite in the tests.
    def _page(self, order_by: str, offset: int, size: int) -> tuple[str, tuple]:
        return f"ORDER BY {order_by} OFFSET ? ROWS FETCH NEXT ? ROWS ONLY", (offset, size)

    def _run(self, work):
        driver = self._db.driver
        try:
            with self._db.transaction() as connection:
                return work(connection.cursor())
        except driver.IntegrityError as exc:
            logger.warning("Integrity error: %s", exc)
            raise ConflictError("The change would break a data rule (e.g. paid amount above total fee).") from exc
        except driver.OperationalError as exc:
            logger.exception("Database operational error")
            raise ServiceUnavailableError("The database is temporarily unavailable. Please retry shortly.") from exc

    # ------------------------------------------------------------------ reads

    def _get(self, cursor, student_id: int) -> dict | None:
        cursor.execute(queries.GET_STUDENT, (student_id,))
        rows = _rows(cursor)
        return rows[0] if rows else None

    def get_student(self, student_id: int) -> dict | None:
        return self._run(lambda c: self._get(c, student_id))

    def list_students(self, as_of: date, status: str | None, course: str | None,
                      page: int, page_size: int) -> tuple[list[dict], int]:
        conditions, params = ["1 = 1"], []
        if status:
            predicate, n_params = STATUS_SQL[status]
            conditions.append(f"({predicate})")
            params.extend([as_of] * n_params)
        if course:
            conditions.append("s.Course = ?")
            params.append(course)
        where = " AND ".join(conditions)
        page_sql, page_params = self._page("s.StudentID", (page - 1) * page_size, page_size)

        def work(cursor):
            cursor.execute(queries.COUNT_STUDENTS.format(where=where), tuple(params))
            total = cursor.fetchone()[0]
            cursor.execute(queries.LIST_STUDENTS.format(columns=queries.STUDENT_COLUMNS, where=where, page=page_sql),
                           (*params, *page_params))
            return _rows(cursor), total

        return self._run(work)

    def list_overdue(self, as_of: date, limit: int) -> list[dict]:
        predicate, _ = STATUS_SQL[OVERDUE]
        page_sql, page_params = self._page("s.DueDate, s.StudentID", 0, limit)

        def work(cursor):
            cursor.execute(queries.LIST_STUDENTS.format(columns=queries.STUDENT_COLUMNS, where=predicate, page=page_sql),
                           (as_of, *page_params))
            return _rows(cursor)

        return self._run(work)

    def list_audit(self, student_id: int, limit: int = 10) -> list[dict]:
        page_sql, page_params = self._page("a.ChangedAt DESC, a.AuditID DESC", 0, limit)

        def work(cursor):
            cursor.execute(queries.LIST_AUDIT.format(page=page_sql), (student_id, *page_params))
            return _rows(cursor)

        return self._run(work)

    def get_admin(self, email: str) -> dict | None:
        def work(cursor):
            cursor.execute(queries.GET_ADMIN_BY_EMAIL, (email.lower(),))
            rows = _rows(cursor)
            return rows[0] if rows else None

        return self._run(work)

    def ping(self) -> None:
        self._run(lambda c: c.execute(queries.HEALTH_CHECK).fetchone())

    # ----------------------------------------------------------------- writes

    def _audit(self, cursor, student_id, action, old: dict, new: dict, changed_by: str, when: datetime):
        cursor.execute(queries.INSERT_AUDIT, (
            student_id, action,
            old["totalFee"], new["totalFee"], old["paidAmount"], new["paidAmount"],
            old["dueDate"], new["dueDate"], changed_by, when,
        ))

    def record_payment(self, student_id: int, amount: Decimal, changed_by: str) -> dict:
        def work(cursor):
            now = _utc_now()
            cursor.execute(queries.RECORD_PAYMENT, (amount, now, student_id, amount))
            if cursor.rowcount == 0:
                current = self._get(cursor, student_id)
                if current is None:
                    raise NotFoundError(f"Student {student_id} was not found.")
                outstanding = (Decimal(str(current["totalFee"])) - Decimal(str(current["paidAmount"]))
                               ).quantize(Decimal("0.01"))
                raise ConflictError("Payment is larger than the outstanding balance.",
                                    {"amount": str(amount), "outstandingBalance": str(outstanding)})
            updated = self._get(cursor, student_id)
            old = {**updated, "paidAmount": Decimal(str(updated["paidAmount"])) - amount}
            self._audit(cursor, student_id, "PAYMENT_RECORDED", old, updated, changed_by, now)
            return updated

        return self._run(work)

    def update_fees(self, student_id: int, changes: dict, changed_by: str) -> dict:
        assignments = ", ".join(f"{UPDATABLE_FEE_FIELDS[f]} = ?" for f in changes)

        def work(cursor):
            old = self._get(cursor, student_id)
            if old is None:
                raise NotFoundError(f"Student {student_id} was not found.")
            total = changes.get("totalFee", Decimal(str(old["totalFee"])))
            paid = changes.get("paidAmount", Decimal(str(old["paidAmount"])))
            if paid > total:
                raise ConflictError("Paid amount cannot exceed the total fee.",
                                    {"totalFee": str(total), "paidAmount": str(paid)})
            now = _utc_now()
            cursor.execute(queries.UPDATE_FEES.format(assignments=assignments),
                           (*changes.values(), now, student_id))
            updated = self._get(cursor, student_id)
            self._audit(cursor, student_id, "FEE_UPDATED", old, updated, changed_by, now)
            return updated

        return self._run(work)
