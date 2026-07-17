import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text

from app.db import engine


def source_lock_key(source_slug: str) -> int:
    """Return a stable signed bigint suitable for PostgreSQL advisory locks."""

    digest = hashlib.sha256(f"ai-tech-radar:collect:{source_slug}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@contextmanager
def source_run_lock(source_slug: str, *, bind: Engine = engine) -> Iterator[bool]:
    """Hold a session-level PostgreSQL lock on a dedicated connection."""

    connection = bind.connect()
    acquired = False
    try:
        acquired = bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": source_lock_key(source_slug)},
            )
        )
        yield acquired
    finally:
        if acquired:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": source_lock_key(source_slug)},
            )
            connection.commit()
        connection.close()
