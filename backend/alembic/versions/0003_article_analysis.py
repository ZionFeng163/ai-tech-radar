"""Add structured article analysis and immutable attempt records.

Revision ID: 0003_article_analysis
Revises: 0002_dedup_event_clusters
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_article_analysis"
down_revision: str | Sequence[str] | None = "0002_dedup_event_clusters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("primary_category", sa.String(length=100)))
    op.add_column(
        "articles",
        sa.Column(
            "analysis_tags",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("articles", sa.Column("importance_score", sa.Float()))
    op.add_column("articles", sa.Column("credibility_score", sa.Float()))
    op.add_column("articles", sa.Column("open_source_status", sa.String(length=30)))
    op.add_column(
        "articles",
        sa.Column(
            "analysis",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("articles", sa.Column("analysis_schema_version", sa.String(length=20)))
    op.add_column("articles", sa.Column("analyzed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_articles_primary_category", "articles", ["primary_category"])
    op.create_index("ix_articles_importance_score", "articles", ["importance_score"])
    op.create_index("ix_articles_open_source_status", "articles", ["open_source_status"])
    op.create_index(
        "ix_articles_analysis_schema_version", "articles", ["analysis_schema_version"]
    )

    op.create_table(
        "analysis_runs",
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("running", "success", "failed", name="analysis_run_status"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "request_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("raw_response", sa.Text()),
        sa.Column(
            "parsed_output",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_summary", sa.Text()),
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
            name="fk_analysis_runs_article_id_articles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_runs"),
    )
    op.create_index(
        "ix_analysis_runs_article_started_at",
        "analysis_runs",
        ["article_id", "started_at"],
    )
    op.create_index(
        "ix_analysis_runs_status_started_at", "analysis_runs", ["status", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_status_started_at", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_article_started_at", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    sa.Enum(name="analysis_run_status").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_articles_analysis_schema_version", table_name="articles")
    op.drop_index("ix_articles_open_source_status", table_name="articles")
    op.drop_index("ix_articles_importance_score", table_name="articles")
    op.drop_index("ix_articles_primary_category", table_name="articles")
    op.drop_column("articles", "analyzed_at")
    op.drop_column("articles", "analysis_schema_version")
    op.drop_column("articles", "analysis")
    op.drop_column("articles", "open_source_status")
    op.drop_column("articles", "credibility_score")
    op.drop_column("articles", "importance_score")
    op.drop_column("articles", "analysis_tags")
    op.drop_column("articles", "primary_category")
