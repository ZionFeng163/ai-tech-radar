"""Add bounded writing workspaces.

Revision ID: 0009_writing_projects
Revises: 0008_remove_retired_sources
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_writing_projects"
down_revision: str | None = "0008_remove_retired_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "writing_projects",
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="new", nullable=False),
        sa.Column(
            "angle_options",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("selected_angle_id", sa.String(length=50), nullable=True),
        sa.Column("output_format", sa.String(length=30), server_default="thread", nullable=False),
        sa.Column(
            "human_input", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("draft_content", sa.Text(), nullable=True),
        sa.Column(
            "review", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", name="uq_writing_projects_article_id"),
    )
    op.create_index("ix_writing_projects_article_id", "writing_projects", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_writing_projects_article_id", table_name="writing_projects")
    op.drop_table("writing_projects")
