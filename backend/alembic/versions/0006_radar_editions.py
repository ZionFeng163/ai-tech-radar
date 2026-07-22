"""Add immutable manual radar editions.

Revision ID: 0006_radar_editions
Revises: 0005_article_heat_signals
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_radar_editions"
down_revision: str | None = "0005_article_heat_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    statuses = ("running", "complete", "failed")
    postgresql.ENUM(*statuses, name="radar_edition_status").create(bind, checkfirst=True)
    status_enum = postgresql.ENUM(
        *statuses, name="radar_edition_status", create_type=False
    )
    op.create_table(
        "radar_editions",
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", status_enum, nullable=False),
        sa.Column(
            "source_results",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("article_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_radar_editions"),
    )
    op.create_index("ix_radar_editions_captured_at", "radar_editions", ["captured_at"])
    op.create_index("ix_radar_editions_status", "radar_editions", ["status"])
    op.create_table(
        "radar_edition_articles",
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["edition_id"], ["radar_editions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("edition_id", "article_id"),
    )
    # Preserve the currently visible radar as the first manual-era snapshot.
    op.execute(
        """
        INSERT INTO radar_editions (
            id, captured_at, finished_at, status, source_results, article_count
        )
        SELECT gen_random_uuid(), now(), now(), 'complete', '[]'::jsonb, count(*)
        FROM articles
        WHERE analysis_schema_version IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO radar_edition_articles (edition_id, article_id)
        SELECT e.id, a.id
        FROM radar_editions e
        CROSS JOIN articles a
        WHERE a.analysis_schema_version IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("radar_edition_articles")
    op.drop_index("ix_radar_editions_status", table_name="radar_editions")
    op.drop_index("ix_radar_editions_captured_at", table_name="radar_editions")
    op.drop_table("radar_editions")
    postgresql.ENUM(name="radar_edition_status").drop(op.get_bind(), checkfirst=True)
