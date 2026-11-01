"""Bounded authoritative write windows across SQLite and row-locking databases."""

import time
from contextlib import contextmanager
from threading import RLock

from django.db import OperationalError, connection, transaction

SQLITE_BUSY_RETRIES = 20
SQLITE_BUSY_DELAY_SECONDS = 0.01
_SQLITE_WRITE_LOCK = RLock()


class DatabaseBusy(RuntimeError):
    pass


def retry_sqlite_busy(operation):
    for retry in range(SQLITE_BUSY_RETRIES + 1):
        try:
            return operation()
        except OperationalError as exc:
            is_busy = connection.vendor == "sqlite" and "locked" in str(exc).lower()
            if not is_busy:
                raise
            if retry == SQLITE_BUSY_RETRIES:
                raise DatabaseBusy(
                    "SQLite could not acquire its bounded authoritative write window."
                ) from exc
            time.sleep(SQLITE_BUSY_DELAY_SECONDS * (retry + 1))


@contextmanager
def authoritative_write():
    """Serialize short SQLite writes without making every request an eager writer."""

    if connection.vendor != "sqlite":
        with transaction.atomic():
            yield
        return
    with _SQLITE_WRITE_LOCK:
        if connection.in_atomic_block:
            with transaction.atomic():
                yield
            return
        with connection.cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
