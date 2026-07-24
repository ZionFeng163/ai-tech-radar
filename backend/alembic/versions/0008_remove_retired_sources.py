"""Remove retired source data and repair canonical URLs.

Revision ID: 0008_remove_retired_sources
Revises: 0007_radar_edition_progress
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_remove_retired_sources"
down_revision: str | None = "0007_radar_edition_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the affected article IDs before deleting sources. Shared articles are
    # retained; articles that only came from a retired source are removed.
    op.execute(
        """
        CREATE TEMP TABLE retired_source_articles (
            article_id uuid PRIMARY KEY
        ) ON COMMIT DROP
        """
    )
    op.execute(
        """
        INSERT INTO retired_source_articles (article_id)
        SELECT DISTINCT raw_items.article_id
        FROM raw_items
        JOIN sources ON sources.id = raw_items.source_id
        WHERE sources.slug IN ('lobsters')
          AND raw_items.article_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO retired_source_articles (article_id)
        SELECT DISTINCT article_id
        FROM article_identities
        WHERE identity_type = 'source_external_id'
          AND identity_value LIKE 'lobsters:%'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DELETE FROM sources WHERE slug IN ('lobsters')")
    op.execute(
        """
        DELETE FROM article_identities
        WHERE (identity_type = 'source_external_id' AND identity_value LIKE 'lobsters:%')
           OR (identity_type = 'canonical_url' AND identity_value LIKE 'https://lobste.rs/%')
        """
    )
    op.execute(
        """
        DELETE FROM articles
        USING retired_source_articles retired
        WHERE articles.id = retired.article_id
          AND NOT EXISTS (
              SELECT 1 FROM raw_items WHERE raw_items.article_id = articles.id
          )
        """
    )

    # Hacker News exposes both a discussion URL and the linked article URL. Old
    # records stored the former despite the adapter already normalizing the latter.
    op.execute(
        """
        UPDATE raw_items
        SET url = metadata->>'target_url'
        FROM sources
        WHERE sources.id = raw_items.source_id
          AND sources.slug = 'hacker-news'
          AND NULLIF(raw_items.metadata->>'target_url', '') IS NOT NULL
        """
    )
    op.execute(
        """
        WITH replacements AS (
            SELECT DISTINCT ON (raw_items.article_id)
                raw_items.article_id,
                raw_items.url,
                raw_items.title,
                raw_items.body,
                raw_items.published_at
            FROM raw_items
            JOIN sources ON sources.id = raw_items.source_id
            WHERE sources.slug = 'hacker-news'
              AND raw_items.article_id IS NOT NULL
            ORDER BY raw_items.article_id, raw_items.fetched_at DESC
        )
        UPDATE articles
        SET canonical_url = replacements.url,
            title = COALESCE(replacements.title, articles.title),
            content = CASE
                WHEN articles.id IN (SELECT article_id FROM retired_source_articles)
                    THEN replacements.body
                ELSE articles.content
            END,
            published_at = LEAST(
                articles.published_at,
                COALESCE(replacements.published_at, articles.published_at)
            )
        FROM replacements
        WHERE articles.id = replacements.article_id
          AND NOT EXISTS (
              SELECT 1
              FROM articles conflict
              WHERE conflict.canonical_url = replacements.url
                AND conflict.id <> articles.id
          )
        """
    )
    op.execute(
        """
        DELETE FROM article_identities
        WHERE identity_type = 'canonical_url'
          AND identity_value LIKE 'https://news.ycombinator.com/item?id=%'
        """
    )
    op.execute(
        """
        INSERT INTO article_identities (
            id, article_id, identity_type, identity_hash, identity_value, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            articles.id,
            'canonical_url',
            encode(sha256(convert_to(articles.canonical_url, 'UTF8')), 'hex'),
            articles.canonical_url,
            now(),
            now()
        FROM articles
        JOIN retired_source_articles retired ON retired.article_id = articles.id
        WHERE articles.canonical_url IS NOT NULL
        ON CONFLICT (identity_type, identity_hash) DO NOTHING
        """
    )

    # Remove retired sources from historical run summaries and synchronize counts
    # after article cleanup so old editions cannot advertise deleted entries.
    op.execute(
        """
        UPDATE radar_editions
        SET source_results = COALESCE(
            (
                SELECT jsonb_agg(item)
                FROM jsonb_array_elements(radar_editions.source_results) item
                WHERE item->>'source' NOT IN ('lobsters')
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
    # Retired provider payloads cannot be reconstructed after deletion.
    pass
