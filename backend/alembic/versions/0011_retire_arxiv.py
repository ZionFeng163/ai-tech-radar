"""Retire the unreliable arXiv collection source.

Revision ID: 0011_retire_arxiv
Revises: 0010_retire_github_releases
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_retire_arxiv"
down_revision: str | None = "0010_retire_github_releases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TEMP TABLE retired_arxiv_articles (
            article_id uuid PRIMARY KEY
        ) ON COMMIT DROP
        """
    )
    op.execute(
        """
        INSERT INTO retired_arxiv_articles (article_id)
        SELECT DISTINCT raw_items.article_id
        FROM raw_items
        JOIN sources ON sources.id = raw_items.source_id
        WHERE sources.slug = 'arxiv'
          AND raw_items.article_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DELETE FROM sources WHERE slug = 'arxiv'")
    op.execute(
        """
        DELETE FROM article_identities
        WHERE identity_type = 'source_external_id'
          AND identity_value LIKE 'arxiv:%'
        """
    )
    op.execute(
        """
        DELETE FROM articles
        USING retired_arxiv_articles retired
        WHERE articles.id = retired.article_id
          AND NOT EXISTS (
              SELECT 1 FROM raw_items WHERE raw_items.article_id = articles.id
          )
        """
    )
    op.execute(
        """
        UPDATE radar_editions
        SET source_results = COALESCE(
            (
                SELECT jsonb_agg(item)
                FROM jsonb_array_elements(radar_editions.source_results) item
                WHERE item->>'source' <> 'arxiv'
            ),
            '[]'::jsonb
        )
        """
    )
    op.execute(
        """
        WITH counts AS (
            SELECT
                radar_editions.id,
                count(radar_edition_articles.article_id)::integer AS article_count
            FROM radar_editions
            LEFT JOIN radar_edition_articles
                ON radar_edition_articles.edition_id = radar_editions.id
            GROUP BY radar_editions.id
        )
        UPDATE radar_editions
        SET article_count = counts.article_count
        FROM counts
        WHERE radar_editions.id = counts.id
        """
    )


def downgrade() -> None:
    # Provider payloads cannot be reconstructed after deletion.
    pass
