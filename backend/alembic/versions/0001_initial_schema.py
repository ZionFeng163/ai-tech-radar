"""Create the unified source and article schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_KINDS = ("arxiv", "github_releases", "hugging_face", "rss", "blog", "other")
ARTICLE_KINDS = (
    "paper",
    "code_repository",
    "release",
    "model",
    "dataset",
    "blog_post",
    "news",
)
FETCH_RUN_STATUSES = ("running", "success", "partial", "failed")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*SOURCE_KINDS, name="source_kind").create(bind, checkfirst=True)
    postgresql.ENUM(*ARTICLE_KINDS, name="article_kind").create(bind, checkfirst=True)
    postgresql.ENUM(*FETCH_RUN_STATUSES, name="fetch_run_status").create(bind, checkfirst=True)

    source_kind = postgresql.ENUM(*SOURCE_KINDS, name="source_kind", create_type=False)
    article_kind = postgresql.ENUM(*ARTICLE_KINDS, name="article_kind", create_type=False)
    fetch_run_status = postgresql.ENUM(
        *FETCH_RUN_STATUSES, name="fetch_run_status", create_type=False
    )

    op.create_table(
        "sources",
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", source_kind, nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "cursor_state",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.UniqueConstraint("slug", name="uq_sources_slug"),
    )

    op.create_table(
        "articles",
        sa.Column("kind", article_kind, nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("license", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_articles"),
        sa.UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),
    )
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"], unique=False)
    op.create_index(
        "ix_articles_kind_published_at", "articles", ["kind", "published_at"], unique=False
    )

    op.create_table(
        "authors",
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "external_ids",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_authors"),
    )
    op.create_index("ix_authors_normalized_name", "authors", ["normalized_name"], unique=False)

    op.create_table(
        "tags",
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("slug", name="uq_tags_slug"),
    )

    op.create_table(
        "fetch_runs",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", fetch_run_status, server_default="running", nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cursor_before",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cursor_after",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("items_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_stored", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_fetch_runs_source_id_sources",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fetch_runs"),
    )
    op.create_index(
        "ix_fetch_runs_source_started_at", "fetch_runs", ["source_id", "started_at"], unique=False
    )

    op.create_table(
        "raw_items",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_id", sa.String(length=500), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "authors", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("license", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_raw_items_article_id_articles",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_raw_items_source_id_sources", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_items"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_raw_items_source_external_id"),
    )
    op.create_index("ix_raw_items_content_hash", "raw_items", ["content_hash"], unique=False)
    op.create_index(
        "ix_raw_items_source_published_at", "raw_items", ["source_id", "published_at"], unique=False
    )

    op.create_table(
        "article_authors",
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_article_authors_article_id_articles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["authors.id"],
            name="fk_article_authors_author_id_authors",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("article_id", "author_id", name="pk_article_authors"),
    )

    op.create_table(
        "article_tags",
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_article_tags_article_id_articles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name="fk_article_tags_tag_id_tags", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("article_id", "tag_id", name="pk_article_tags"),
    )


def downgrade() -> None:
    op.drop_table("article_tags")
    op.drop_table("article_authors")
    op.drop_index("ix_raw_items_source_published_at", table_name="raw_items")
    op.drop_index("ix_raw_items_content_hash", table_name="raw_items")
    op.drop_table("raw_items")
    op.drop_index("ix_fetch_runs_source_started_at", table_name="fetch_runs")
    op.drop_table("fetch_runs")
    op.drop_table("tags")
    op.drop_index("ix_authors_normalized_name", table_name="authors")
    op.drop_table("authors")
    op.drop_index("ix_articles_kind_published_at", table_name="articles")
    op.drop_index("ix_articles_content_hash", table_name="articles")
    op.drop_table("articles")
    op.drop_table("sources")

    bind = op.get_bind()
    postgresql.ENUM(name="fetch_run_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="article_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="source_kind").drop(bind, checkfirst=True)
