"""Database access: connection handling, transactions and transient retries."""

import logging
import time
from contextlib import contextmanager

from .errors import ServiceUnavailableError

logger = logging.getLogger(__name__)

# Azure SQL errors that are worth retrying: database waking from auto-pause
# (40613), failover/reconfiguration (40197, 40501, 49918-49920), login
# timing (4060, 4221), resource limits (10928, 10929), plus ODBC
# timeout / link-failure SQLSTATEs.
TRANSIENT_ERROR_MARKERS = (
    "40613", "40197", "40501", "49918", "49919", "49920",
    "4060", "4221", "10928", "10929",
    "HYT00", "HYT01", "08S01", "08001",
)


def is_transient(exc: Exception) -> bool:
    text = " ".join(str(arg) for arg in getattr(exc, "args", ()))
    return any(marker in text for marker in TRANSIENT_ERROR_MARKERS)


class SqlServerDatabase:
    """Opens a pyodbc connection per unit of work.

    pyodbc enables ODBC connection pooling by default, so "open per request"
    reuses physical connections between invocations on the same worker.
    """

    def __init__(self, connection_string: str, max_attempts: int = 3, base_delay_seconds: float = 1.0):
        self._connection_string = connection_string
        self._max_attempts = max_attempts
        self._base_delay = base_delay_seconds

        import pyodbc  # imported lazily so unit tests don't need the ODBC driver

        self.driver = pyodbc

    def _connect(self):
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self.driver.connect(self._connection_string, autocommit=False)
            except self.driver.Error as exc:
                if attempt < self._max_attempts and is_transient(exc):
                    delay = self._base_delay * 2 ** (attempt - 1)
                    logger.warning("Transient SQL connect error (attempt %s/%s); retrying in %ss",
                                   attempt, self._max_attempts, delay)
                    time.sleep(delay)
                    continue
                logger.exception("Could not connect to the database")
                raise ServiceUnavailableError("The database is temporarily unavailable. Please retry shortly.") from exc
        raise AssertionError("unreachable")

    @contextmanager
    def transaction(self):
        """Commit on success, roll back on any error, always close.

        Note: pyodbc's own `with connection:` commits but does NOT close,
        which is why this is written out explicitly.
        """
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
