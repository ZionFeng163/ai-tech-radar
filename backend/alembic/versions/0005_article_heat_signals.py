"""Add reader-facing brief and heat signal fields.

Revision ID: 0005_article_heat_signals
Revises: 0004_article_search_indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_article_heat_signals"
down_revision: str | None = "0004_article_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("heat_score", sa.Float()))
    op.add_column("articles", sa.Column("signal_type", sa.String(length=30)))
    op.add_column("articles", sa.Column("technical_overview", sa.Text()))
    op.add_column("articles", sa.Column("novelty_summary", sa.Text()))
    op.add_column(
        "articles",
        sa.Column(
            "heat_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("ix_articles_heat_score", "articles", ["heat_score"])
    op.create_index("ix_articles_signal_type", "articles", ["signal_type"])


def downgrade() -> None:
    op.drop_index("ix_articles_signal_type", table_name="articles")
    op.drop_index("ix_articles_heat_score", table_name="articles")
    op.drop_column("articles", "heat_reasons")
    op.drop_column("articles", "novelty_summary")
    op.drop_column("articles", "technical_overview")
    op.drop_column("articles", "signal_type")
    op.drop_column("articles", "heat_score")
