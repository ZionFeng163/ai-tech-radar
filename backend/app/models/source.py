from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.domain import FetchRunStatus, SourceKind
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, enum_values, utc_now

if TYPE_CHECKING:
    from app.models.article import Article


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[SourceKind] = mapped_column(
        Enum(
            SourceKind,
            name="source_kind",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    base_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    cursor_state: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)

    raw_items: Mapped[list[RawItem]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    fetch_runs: Mapped[list[FetchRun]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class RawItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "raw_items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_items_source_external_id"),
        Index("ix_raw_items_source_published_at", "source_id", "published_at"),
    )

    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("articles.id", ondelete="SET NULL")
    )
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list, nullable=False)
    license: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    source: Mapped[Source] = relationship(back_populates="raw_items")
    article: Mapped[Article | None] = relationship(back_populates="raw_items")


class FetchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fetch_runs"
    __table_args__ = (Index("ix_fetch_runs_source_started_at", "source_id", "started_at"),)

    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[FetchRunStatus] = mapped_column(
        Enum(
            FetchRunStatus,
            name="fetch_run_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=FetchRunStatus.RUNNING,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_before: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    cursor_after: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    items_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_stored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    run_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    source: Mapped[Source] = relationship(back_populates="fetch_runs")
