from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.domain import ArticleKind
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, enum_values

if TYPE_CHECKING:
    from app.models.source import RawItem


article_authors = Table(
    "article_authors",
    Base.metadata,
    Column(
        "article_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "author_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

article_tags = Table(
    "article_tags",
    Base.metadata,
    Column(
        "article_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),
        Index("ix_articles_kind_published_at", "kind", "published_at"),
    )

    kind: Mapped[ArticleKind] = mapped_column(
        Enum(
            ArticleKind,
            name="article_kind",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    raw_items: Mapped[list[RawItem]] = relationship(back_populates="article")
    authors: Mapped[list[Author]] = relationship(
        secondary=article_authors, back_populates="articles"
    )
    tags: Mapped[list[Tag]] = relationship(secondary=article_tags, back_populates="articles")


class Author(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "authors"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(Text)
    external_ids: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)

    articles: Mapped[list[Article]] = relationship(
        secondary=article_authors, back_populates="authors"
    )


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    articles: Mapped[list[Article]] = relationship(secondary=article_tags, back_populates="tags")
