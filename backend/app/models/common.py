from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


def enum_values(enum_class: type[Enum]) -> list[str]:
    return [str(member.value) for member in enum_class]


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )
