from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.domain import RadarEditionStatus
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, enum_values, utc_now

if TYPE_CHECKING:
    from app.models.article import Article


radar_edition_articles = Table(
    "radar_edition_articles",
    Base.metadata,
    Column(
        "edition_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("radar_editions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "article_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class RadarEdition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "radar_editions"

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RadarEditionStatus] = mapped_column(
        Enum(
            RadarEditionStatus,
            name="radar_edition_status",
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=RadarEditionStatus.RUNNING,
        nullable=False,
        index=True,
    )
    source_results: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    article_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)

    articles: Mapped[list[Article]] = relationship(
        secondary=radar_edition_articles, back_populates="editions"
    )
