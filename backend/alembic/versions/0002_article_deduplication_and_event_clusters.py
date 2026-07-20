"""Add article identities, embeddings, and event clusters.

Revision ID: 0002_dedup_event_clusters
Revises: 0001_initial_schema
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_dedup_event_clusters"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_clusters",
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "centroid", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("member_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "explanation",
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
        sa.PrimaryKeyConstraint("id", name="pk_event_clusters"),
    )
    op.create_index(
        "ix_event_clusters_last_published_at",
        "event_clusters",
        ["last_published_at"],
        unique=False,
    )

    op.add_column(
        "articles",
        sa.Column("event_cluster_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("articles", sa.Column("title_fingerprint", sa.String(length=64), nullable=True))
    op.add_column(
        "articles",
        sa.Column(
            "embedding", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
    )
    op.create_foreign_key(
        "fk_articles_event_cluster_id_event_clusters",
        "articles",
        "event_clusters",
        ["event_cluster_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_articles_event_cluster_id", "articles", ["event_cluster_id"], unique=False)
    op.create_index(
        "ix_articles_title_fingerprint", "articles", ["title_fingerprint"], unique=False
    )

    op.create_table(
        "article_identities",
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_type", sa.String(length=50), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_value", sa.Text(), nullable=False),
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
            name="fk_article_identities_article_id_articles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_article_identities"),
        sa.UniqueConstraint("identity_type", "identity_hash", name="uq_article_identities_key"),
    )
    op.create_index(
        "ix_article_identities_article_id", "article_identities", ["article_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_article_identities_article_id", table_name="article_identities")
    op.drop_table("article_identities")
    op.drop_index("ix_articles_title_fingerprint", table_name="articles")
    op.drop_index("ix_articles_event_cluster_id", table_name="articles")
    op.drop_constraint(
        "fk_articles_event_cluster_id_event_clusters", "articles", type_="foreignkey"
    )
    op.drop_column("articles", "embedding")
    op.drop_column("articles", "title_fingerprint")
    op.drop_column("articles", "event_cluster_id")
    op.drop_index("ix_event_clusters_last_published_at", table_name="event_clusters")
    op.drop_table("event_clusters")
