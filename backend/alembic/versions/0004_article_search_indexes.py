"""Add article listing and full-text search indexes.

Revision ID: 0004_article_search_indexes
Revises: 0003_article_analysis
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_article_search_indexes"
down_revision: str | Sequence[str] | None = "0003_article_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_articles_published_at_id",
        "articles",
        ["published_at", "id"],
    )
    op.create_index("ix_raw_items_article_id", "raw_items", ["article_id"])
    op.execute(
        """
        CREATE INDEX ix_articles_search_document
        ON articles USING gin (
          to_tsvector(
            'simple'::regconfig,
            COALESCE(title, '') || ' ' || COALESCE(summary, '') || ' ' || COALESCE(content, '')
          )
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_articles_search_document", table_name="articles")
    op.drop_index("ix_raw_items_article_id", table_name="raw_items")
    op.drop_index("ix_articles_published_at_id", table_name="articles")
