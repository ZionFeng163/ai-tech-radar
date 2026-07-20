from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
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


class EventCluster(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_clusters"
    __table_args__ = (Index("ix_event_clusters_last_published_at", "last_published_at"),)

    label: Mapped[str] = mapped_column(Text, nullable=False)
    centroid: Mapped[list[float]] = mapped_column(JSONB, default=list, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    explanation: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)

    articles: Mapped[list[Article]] = relationship(back_populates="event_cluster")


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),
        Index("ix_articles_kind_published_at", "kind", "published_at"),
    )

    event_cluster_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("event_clusters.id", ondelete="SET NULL"),
        index=True,
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
    title_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(JSONB, default=list, nullable=False)
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    raw_items: Mapped[list[RawItem]] = relationship(back_populates="article")
    event_cluster: Mapped[EventCluster | None] = relationship(back_populates="articles")
    identities: Mapped[list[ArticleIdentity]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
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


class ArticleIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_identities"
    __table_args__ = (
        UniqueConstraint("identity_type", "identity_hash", name="uq_article_identities_key"),
        Index("ix_article_identities_article_id", "article_id"),
    )

    article_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_value: Mapped[str] = mapped_column(Text, nullable=False)

    article: Mapped[Article] = relationship(back_populates="identities")
