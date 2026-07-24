from dataclasses import asdict, dataclass
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class CleanupReport:
    keep_editions: int
    keep_fetch_runs_per_source: int
    keep_analysis_runs_per_article: int
    blocked: bool
    running_editions: int
    running_fetch_runs: int
    running_analysis_runs: int
    editions: int
    articles: int
    raw_items: int
    fetch_runs: int
    analysis_runs: int
    authors: int
    tags: int
    event_clusters: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class RetentionCleanupService:
    KEEP_FETCH_RUNS_PER_SOURCE = 20
    KEEP_ANALYSIS_RUNS_PER_ARTICLE = 5

    def preview(self, session: Session, *, keep_editions: int) -> CleanupReport:
        self._validate_keep_editions(keep_editions)
        row = session.execute(
            text(self._preview_sql()),
            {
                "keep_editions": keep_editions,
                "keep_fetch_runs": self.KEEP_FETCH_RUNS_PER_SOURCE,
                "keep_analysis_runs": self.KEEP_ANALYSIS_RUNS_PER_ARTICLE,
            },
        ).mappings().one()
        running_editions = int(row["running_editions"])
        running_fetch_runs = int(row["running_fetch_runs"])
        running_analysis_runs = int(row["running_analysis_runs"])
        return CleanupReport(
            keep_editions=keep_editions,
            keep_fetch_runs_per_source=self.KEEP_FETCH_RUNS_PER_SOURCE,
            keep_analysis_runs_per_article=self.KEEP_ANALYSIS_RUNS_PER_ARTICLE,
            blocked=bool(running_editions or running_fetch_runs or running_analysis_runs),
            running_editions=running_editions,
            running_fetch_runs=running_fetch_runs,
            running_analysis_runs=running_analysis_runs,
            editions=int(row["editions"]),
            articles=int(row["articles"]),
            raw_items=int(row["raw_items"]),
            fetch_runs=int(row["fetch_runs"]),
            analysis_runs=int(row["analysis_runs"]),
            authors=int(row["authors"]),
            tags=int(row["tags"]),
            event_clusters=int(row["event_clusters"]),
        )

    def run(self, session: Session, *, keep_editions: int) -> CleanupReport:
        preview = self.preview(session, keep_editions=keep_editions)
        if preview.blocked:
            raise RuntimeError("cleanup is unavailable while collection or analysis is running")

        try:
            session.execute(
                text(
                    """
                    CREATE TEMP TABLE cleanup_retained_editions (
                        edition_id uuid PRIMARY KEY
                    ) ON COMMIT DROP
                    """
                )
            )
            session.execute(
                text(
                    """
                    CREATE TEMP TABLE cleanup_stale_articles (
                        article_id uuid PRIMARY KEY
                    ) ON COMMIT DROP
                    """
                )
            )
            session.execute(
                text(
                    """
                    INSERT INTO cleanup_retained_editions (edition_id)
                    SELECT id FROM radar_editions WHERE status = 'running'
                    UNION
                    SELECT id FROM (
                        SELECT id
                        FROM radar_editions
                        WHERE status = 'complete'
                        ORDER BY captured_at DESC, id DESC
                        LIMIT :keep_editions
                    ) recent
                    """
                ),
                {"keep_editions": keep_editions},
            )
            session.execute(
                text(
                    """
                    INSERT INTO cleanup_stale_articles (article_id)
                    SELECT articles.id
                    FROM articles
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM radar_edition_articles
                        JOIN cleanup_retained_editions
                          ON cleanup_retained_editions.edition_id =
                             radar_edition_articles.edition_id
                        WHERE radar_edition_articles.article_id = articles.id
                    )
                    """
                )
            )

            deleted_raw_items = self._delete_count(
                session,
                """
                DELETE FROM raw_items
                WHERE article_id IS NULL
                   OR article_id IN (SELECT article_id FROM cleanup_stale_articles)
                """,
            )
            deleted_analysis_runs = self._delete_count(
                session,
                """
                WITH ranked AS (
                    SELECT
                        id,
                        article_id,
                        row_number() OVER (
                            PARTITION BY article_id ORDER BY started_at DESC, id DESC
                        ) AS position
                    FROM analysis_runs
                )
                DELETE FROM analysis_runs
                USING ranked
                WHERE analysis_runs.id = ranked.id
                  AND (
                      ranked.article_id IN (
                          SELECT article_id FROM cleanup_stale_articles
                      )
                      OR ranked.position > :keep_analysis_runs
                  )
                """,
                {"keep_analysis_runs": self.KEEP_ANALYSIS_RUNS_PER_ARTICLE},
            )
            deleted_editions = self._delete_count(
                session,
                """
                DELETE FROM radar_editions
                WHERE id NOT IN (SELECT edition_id FROM cleanup_retained_editions)
                """,
            )
            deleted_articles = self._delete_count(
                session,
                """
                DELETE FROM articles
                WHERE id IN (SELECT article_id FROM cleanup_stale_articles)
                """,
            )
            deleted_fetch_runs = self._delete_count(
                session,
                """
                WITH ranked AS (
                    SELECT
                        id,
                        row_number() OVER (
                            PARTITION BY source_id ORDER BY started_at DESC, id DESC
                        ) AS position
                    FROM fetch_runs
                )
                DELETE FROM fetch_runs
                USING ranked
                WHERE fetch_runs.id = ranked.id
                  AND ranked.position > :keep_fetch_runs
                """,
                {"keep_fetch_runs": self.KEEP_FETCH_RUNS_PER_SOURCE},
            )
            deleted_authors = self._delete_count(
                session,
                "DELETE FROM authors WHERE NOT EXISTS "
                "(SELECT 1 FROM article_authors WHERE article_authors.author_id = authors.id)",
            )
            deleted_tags = self._delete_count(
                session,
                "DELETE FROM tags WHERE NOT EXISTS "
                "(SELECT 1 FROM article_tags WHERE article_tags.tag_id = tags.id)",
            )
            deleted_clusters = self._delete_count(
                session,
                "DELETE FROM event_clusters WHERE NOT EXISTS "
                "(SELECT 1 FROM articles WHERE articles.event_cluster_id = event_clusters.id)",
            )
            session.execute(
                text(
                    """
                    WITH cluster_stats AS (
                        SELECT
                            event_cluster_id,
                            count(*)::integer AS member_count,
                            min(published_at) AS first_published_at,
                            max(published_at) AS last_published_at
                        FROM articles
                        WHERE event_cluster_id IS NOT NULL
                        GROUP BY event_cluster_id
                    )
                    UPDATE event_clusters
                    SET member_count = cluster_stats.member_count,
                        first_published_at = cluster_stats.first_published_at,
                        last_published_at = cluster_stats.last_published_at
                    FROM cluster_stats
                    WHERE event_clusters.id = cluster_stats.event_cluster_id
                    """
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

        return CleanupReport(
            keep_editions=keep_editions,
            keep_fetch_runs_per_source=self.KEEP_FETCH_RUNS_PER_SOURCE,
            keep_analysis_runs_per_article=self.KEEP_ANALYSIS_RUNS_PER_ARTICLE,
            blocked=False,
            running_editions=0,
            running_fetch_runs=0,
            running_analysis_runs=0,
            editions=deleted_editions,
            articles=deleted_articles,
            raw_items=deleted_raw_items,
            fetch_runs=deleted_fetch_runs,
            analysis_runs=deleted_analysis_runs,
            authors=deleted_authors,
            tags=deleted_tags,
            event_clusters=deleted_clusters,
        )

    @staticmethod
    def _delete_count(
        session: Session,
        statement: str,
        parameters: dict[str, object] | None = None,
    ) -> int:
        result = session.execute(text(statement), parameters or {})
        rowcount = cast(CursorResult[Any], result).rowcount
        return max(0, rowcount or 0)

    @staticmethod
    def _validate_keep_editions(value: int) -> None:
        if not 1 <= value <= 50:
            raise ValueError("keep_editions must be between 1 and 50")

    @staticmethod
    def _preview_sql() -> str:
        return """
            WITH recent_editions AS (
                SELECT id
                FROM radar_editions
                WHERE status = 'complete'
                ORDER BY captured_at DESC, id DESC
                LIMIT :keep_editions
            ),
            retained_editions AS (
                SELECT id FROM radar_editions WHERE status = 'running'
                UNION SELECT id FROM recent_editions
            ),
            retained_articles AS (
                SELECT DISTINCT radar_edition_articles.article_id
                FROM radar_edition_articles
                JOIN retained_editions
                  ON retained_editions.id = radar_edition_articles.edition_id
            ),
            stale_articles AS (
                SELECT id FROM articles
                WHERE id NOT IN (SELECT article_id FROM retained_articles)
            ),
            ranked_fetch_runs AS (
                SELECT
                    id,
                    status,
                    row_number() OVER (
                        PARTITION BY source_id ORDER BY started_at DESC, id DESC
                    ) AS position
                FROM fetch_runs
            ),
            ranked_analysis_runs AS (
                SELECT
                    id,
                    article_id,
                    status,
                    row_number() OVER (
                        PARTITION BY article_id ORDER BY started_at DESC, id DESC
                    ) AS position
                FROM analysis_runs
            )
            SELECT
                (SELECT count(*) FROM radar_editions WHERE status = 'running')
                    AS running_editions,
                (SELECT count(*) FROM fetch_runs WHERE status = 'running')
                    AS running_fetch_runs,
                (SELECT count(*) FROM analysis_runs WHERE status = 'running')
                    AS running_analysis_runs,
                (SELECT count(*) FROM radar_editions
                    WHERE id NOT IN (SELECT id FROM retained_editions)) AS editions,
                (SELECT count(*) FROM stale_articles) AS articles,
                (SELECT count(*) FROM raw_items
                    WHERE article_id IS NULL
                       OR article_id IN (SELECT id FROM stale_articles)) AS raw_items,
                (SELECT count(*) FROM ranked_fetch_runs
                    WHERE position > :keep_fetch_runs AND status <> 'running') AS fetch_runs,
                (SELECT count(*) FROM ranked_analysis_runs
                    WHERE (article_id IN (SELECT id FROM stale_articles)
                           OR position > :keep_analysis_runs)
                      AND status <> 'running') AS analysis_runs,
                (SELECT count(*) FROM authors
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM article_authors
                        JOIN retained_articles
                          ON retained_articles.article_id = article_authors.article_id
                        WHERE article_authors.author_id = authors.id
                    )) AS authors,
                (SELECT count(*) FROM tags
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM article_tags
                        JOIN retained_articles
                          ON retained_articles.article_id = article_tags.article_id
                        WHERE article_tags.tag_id = tags.id
                    )) AS tags,
                (SELECT count(*) FROM event_clusters
                    WHERE NOT EXISTS (
                        SELECT 1 FROM articles
                        JOIN retained_articles
                          ON retained_articles.article_id = articles.id
                        WHERE articles.event_cluster_id = event_clusters.id
                    )) AS event_clusters
        """
