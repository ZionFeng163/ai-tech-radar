"""Retire GitHub release bundles from the editorial radar.

Revision ID: 0010_retire_github_releases
Revises: 0009_writing_projects
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_retire_github_releases"
down_revision: str | None = "0009_writing_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TEMP TABLE retired_github_release_articles (
            article_id uuid PRIMARY KEY
        ) ON COMMIT DROP
        """
    )
    op.execute(
        """
        INSERT INTO retired_github_release_articles (article_id)
        SELECT DISTINCT raw_items.article_id
        FROM raw_items
        JOIN sources ON sources.id = raw_items.source_id
        WHERE sources.slug = 'github-releases'
          AND raw_items.article_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DELETE FROM sources WHERE slug = 'github-releases'")
    op.execute(
        """
        DELETE FROM article_identities
        WHERE identity_type = 'source_external_id'
          AND identity_value LIKE 'github-releases:%'
        """
    )
    op.execute(
        """
        DELETE FROM articles
        USING retired_github_release_articles retired
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
                WHERE item->>'source' <> 'github-releases'
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
        SET article_count = counts.article_count,
            progress = CASE
                WHEN radar_editions.status = 'complete' THEN
                    jsonb_build_object(
                        'stage', 'complete',
                        'completed', counts.article_count,
                        'total', counts.article_count,
                        'message', '历史期次已完成，共收录 ' || counts.article_count || ' 条'
                    )
                ELSE radar_editions.progress
            END
        FROM counts
        WHERE radar_editions.id = counts.id
        """
    )


def downgrade() -> None:
    # Provider payloads cannot be reconstructed after deletion.
    pass
