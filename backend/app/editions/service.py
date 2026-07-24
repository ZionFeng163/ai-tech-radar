import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.analysis import AnalysisConfig, AnalysisPipeline
from app.collection.registry import SourceRegistry
from app.collection.runner import CollectionRunner
from app.db import SessionLocal
from app.domain import RadarEditionStatus
from app.models import Article, FetchRun, RadarEdition, RawItem
from app.processing import NormalizationPipeline

LOGGER = logging.getLogger(__name__)


class ManualRadarService:
    DEFAULT_SOURCE_LIMITS = {
        "hacker-news": 15,
        "dev-community": 12,
        "github-releases": 8,
        "arxiv": 5,
        "hugging-face": 5,
    }

    def __init__(
        self,
        *,
        items_per_source: int = 10,
        source_limits: dict[str, int] | None = None,
    ) -> None:
        self.items_per_source = items_per_source
        self.source_limits = source_limits or self.DEFAULT_SOURCE_LIMITS

    def create(self) -> UUID:
        with SessionLocal() as session:
            edition = RadarEdition(status=RadarEditionStatus.RUNNING)
            session.add(edition)
            session.commit()
            return edition.id

    async def run(self, edition_id: UUID) -> None:
        source_results: list[dict[str, object]] = []
        raw_item_ids: set[UUID] = set()
        try:
            registry = SourceRegistry()
            runner = CollectionRunner(registry)
            for source_slug in registry.slugs:
                try:
                    result = await runner.run(
                        source_slug,
                        limit=self.source_limits.get(source_slug, self.items_per_source),
                        trigger=f"manual-edition:{edition_id}",
                    )
                except Exception as exc:
                    LOGGER.exception("manual collection failed for source=%s", source_slug)
                    source_results.append(
                        {"source": source_slug, "status": "failed", "error": str(exc)[:500]}
                    )
                    continue
                source_results.append(result.as_dict())
                if result.run_id:
                    raw_item_ids.update(self._raw_items_for_run(UUID(result.run_id)))

            if raw_item_ids:
                NormalizationPipeline().run(raw_item_ids=list(raw_item_ids))
            article_ids = self._article_ids(raw_item_ids)
            analyzer = AnalysisPipeline(AnalysisConfig.from_file(), depth="brief")
            for article_id in self._articles_missing_brief(article_ids):
                await analyzer.run_article(article_id)
            self._complete(edition_id, article_ids, source_results)
        except Exception as exc:
            LOGGER.exception("manual radar edition failed edition=%s", edition_id)
            self._fail(edition_id, source_results, str(exc))

    @staticmethod
    def _raw_items_for_run(run_id: UUID) -> list[UUID]:
        with SessionLocal() as session:
            run = session.get(FetchRun, run_id)
            if run is None or run.finished_at is None:
                return []
            return list(
                session.scalars(
                    select(RawItem.id).where(
                        RawItem.source_id == run.source_id,
                        RawItem.fetched_at >= run.started_at,
                        RawItem.fetched_at <= run.finished_at,
                    )
                )
            )

    @staticmethod
    def _article_ids(raw_item_ids: set[UUID]) -> set[UUID]:
        if not raw_item_ids:
            return set()
        with SessionLocal() as session:
            return {
                article_id
                for article_id in session.scalars(
                    select(RawItem.article_id).where(RawItem.id.in_(raw_item_ids))
                )
                if article_id is not None
            }

    @staticmethod
    def _articles_missing_brief(article_ids: set[UUID]) -> list[UUID]:
        if not article_ids:
            return []
        with SessionLocal() as session:
            return list(
                session.scalars(
                    select(Article.id)
                    .where(
                        Article.id.in_(article_ids),
                        Article.technical_overview.is_(None),
                    )
                    .order_by(Article.published_at.desc())
                )
            )

    @staticmethod
    def _complete(
        edition_id: UUID,
        article_ids: set[UUID],
        source_results: list[dict[str, object]],
    ) -> None:
        with SessionLocal() as session:
            edition = session.scalar(
                select(RadarEdition)
                .options(selectinload(RadarEdition.articles))
                .where(RadarEdition.id == edition_id)
            )
            if edition is None:
                return
            edition.articles = (
                list(session.scalars(select(Article).where(Article.id.in_(article_ids))))
                if article_ids
                else []
            )
            edition.article_count = len(article_ids)
            edition.source_results = source_results
            edition.status = RadarEditionStatus.COMPLETE
            edition.finished_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _fail(
        edition_id: UUID,
        source_results: list[dict[str, object]],
        error: str,
    ) -> None:
        with SessionLocal() as session:
            edition = session.get(RadarEdition, edition_id)
            if edition is None:
                return
            edition.status = RadarEditionStatus.FAILED
            edition.finished_at = datetime.now(UTC)
            edition.source_results = source_results
            edition.error_summary = error[:2_000]
            session.commit()
