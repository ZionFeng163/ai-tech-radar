import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.analysis import AnalysisConfig, AnalysisPipeline
from app.api.queries import ArticleFilters, count_articles
from app.collection.registry import SourceRegistry
from app.collection.runner import CollectionRunner
from app.db import SessionLocal
from app.domain import RadarEditionStatus
from app.models import AnalysisRun, Article, FetchRun, RadarEdition, RawItem
from app.processing import NormalizationPipeline

LOGGER = logging.getLogger(__name__)


class ManualRadarService:
    DEFAULT_SOURCE_LIMITS = {
        "hacker-news": 30,
        "dev-community": 12,
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
            edition = RadarEdition(
                status=RadarEditionStatus.RUNNING,
                progress={
                    "stage": "queued",
                    "completed": 0,
                    "total": 0,
                    "message": "等待开始",
                },
            )
            session.add(edition)
            session.commit()
            return edition.id

    async def run(self, edition_id: UUID) -> None:
        source_results: list[dict[str, object]] = []
        raw_item_ids: set[UUID] = set()
        try:
            registry = SourceRegistry()
            runner = CollectionRunner(registry)
            source_slugs = registry.slugs
            self._set_progress(
                edition_id,
                stage="collecting",
                completed=0,
                total=len(source_slugs),
                message="准备抓取 API 来源",
                source_results=source_results,
            )
            for source_index, source_slug in enumerate(source_slugs):
                source_name = registry.get(source_slug).descriptor.name
                self._set_progress(
                    edition_id,
                    stage="collecting",
                    completed=source_index,
                    total=len(source_slugs),
                    message=f"正在抓取 {source_name}",
                    current_source=source_slug,
                    source_results=source_results,
                )
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
                else:
                    source_results.append(result.as_dict())
                    if result.run_id:
                        raw_item_ids.update(self._raw_items_for_run(UUID(result.run_id)))
                self._set_progress(
                    edition_id,
                    stage="collecting",
                    completed=source_index + 1,
                    total=len(source_slugs),
                    message=f"已完成 {source_name}",
                    source_results=source_results,
                )

            if raw_item_ids:
                self._set_progress(
                    edition_id,
                    stage="normalizing",
                    completed=0,
                    total=len(raw_item_ids),
                    message=f"正在整理 {len(raw_item_ids)} 条 API 数据",
                    source_results=source_results,
                )
                NormalizationPipeline().run(raw_item_ids=list(raw_item_ids))
                self._set_progress(
                    edition_id,
                    stage="normalizing",
                    completed=len(raw_item_ids),
                    total=len(raw_item_ids),
                    message="API 数据整理完成",
                    source_results=source_results,
                )
            article_ids = self._article_ids(raw_item_ids)
            self._attach_articles(edition_id, article_ids)
            analyzer = AnalysisPipeline(AnalysisConfig.from_file(), depth="brief")
            missing_briefs = self._articles_missing_brief(article_ids)
            self._set_progress(
                edition_id,
                stage="analyzing",
                completed=0,
                total=len(missing_briefs),
                message=(
                    f"准备生成 {len(missing_briefs)} 条快速概览"
                    if missing_briefs
                    else "本期内容已有快速概览"
                ),
                source_results=source_results,
            )
            analysis_attempted = 0
            analysis_failed = 0
            blocking_error: str | None = None
            for analysis_index, article_id in enumerate(missing_briefs, start=1):
                analysis_attempted += 1
                succeeded, _ = await analyzer.run_article(article_id)
                if not succeeded:
                    analysis_failed += 1
                    latest_error = self._latest_analysis_failure(article_id)
                    if latest_error and self._is_systemic_analysis_failure(latest_error):
                        blocking_error = self._friendly_analysis_error(latest_error)
                self._set_progress(
                    edition_id,
                    stage="analyzing",
                    completed=analysis_index,
                    total=len(missing_briefs),
                    message=(
                        blocking_error
                        or f"正在生成快速概览 {analysis_index}/{len(missing_briefs)}"
                    ),
                    source_results=source_results,
                )
                if blocking_error:
                    break

            analyzed_count = self._brief_count(article_ids)
            visible_count = self._visible_count(edition_id)
            analysis_skipped = max(0, len(missing_briefs) - analysis_attempted)
            source_warning = self._source_failure_summary(source_results)
            warnings = [
                warning
                for warning in (
                    blocking_error,
                    (
                        f"{analysis_failed} 条快速概览生成失败"
                        if analysis_failed and not blocking_error
                        else None
                    ),
                    source_warning,
                )
                if warning
            ]
            warning_summary = "；".join(warnings) or None
            if blocking_error and visible_count == 0:
                self._fail(
                    edition_id,
                    source_results,
                    warning_summary or blocking_error,
                    collected_count=len(article_ids),
                    analyzed_count=analyzed_count,
                    visible_count=visible_count,
                    analysis_failed=analysis_failed,
                    analysis_skipped=analysis_skipped,
                )
            elif not article_ids and source_warning:
                self._fail(
                    edition_id,
                    source_results,
                    source_warning,
                    collected_count=0,
                    analyzed_count=0,
                    visible_count=0,
                    analysis_failed=0,
                    analysis_skipped=0,
                )
            else:
                self._complete(
                    edition_id,
                    article_ids,
                    source_results,
                    analyzed_count=analyzed_count,
                    visible_count=visible_count,
                    analysis_failed=analysis_failed,
                    analysis_skipped=analysis_skipped,
                    warning_summary=warning_summary,
                )
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
    def _attach_articles(edition_id: UUID, article_ids: set[UUID]) -> None:
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
            session.commit()

    @staticmethod
    def _brief_count(article_ids: set[UUID]) -> int:
        if not article_ids:
            return 0
        with SessionLocal() as session:
            return len(
                list(
                    session.scalars(
                        select(Article.id).where(
                            Article.id.in_(article_ids),
                            Article.technical_overview.is_not(None),
                        )
                    )
                )
            )

    @staticmethod
    def _visible_count(edition_id: UUID) -> int:
        with SessionLocal() as session:
            return count_articles(session, ArticleFilters(edition_id=edition_id))

    @staticmethod
    def _latest_analysis_failure(article_id: UUID) -> str | None:
        with SessionLocal() as session:
            run = session.scalar(
                select(AnalysisRun)
                .where(
                    AnalysisRun.article_id == article_id,
                    AnalysisRun.error_summary.is_not(None),
                )
                .order_by(AnalysisRun.started_at.desc())
                .limit(1)
            )
            return run.error_summary if run is not None else None

    @staticmethod
    def _is_systemic_analysis_failure(error: str) -> bool:
        markers = (
            "AllocationQuota",
            "Free quota exhausted",
            "InvalidApiKey",
            "HTTP 401",
            "HTTP 403",
            "HTTP 429",
            "Throttling",
        )
        return any(marker.casefold() in error.casefold() for marker in markers)

    @staticmethod
    def _friendly_analysis_error(error: str) -> str:
        lowered = error.casefold()
        if "allocationquota.freetieronly" in lowered or "free quota exhausted" in lowered:
            return (
                "百炼免费额度已耗尽；请充值或在百炼控制台关闭“仅使用免费额度”后重试"
            )
        if "http 401" in lowered or "invalidapikey" in lowered:
            return "百炼 API Key 无效，请更新配置后重试"
        if "http 429" in lowered or "throttling" in lowered:
            return "百炼请求频率受限，本期分析已停止，请稍后重试"
        if "http 403" in lowered:
            return "百炼拒绝了模型访问，请检查模型权限、额度和账号设置"
        return error[:500]

    @staticmethod
    def _source_failure_summary(source_results: list[dict[str, object]]) -> str | None:
        failures: list[str] = []
        for result in source_results:
            if result.get("status") != "failed":
                continue
            source = str(result.get("source") or "未知来源")
            error = str(result.get("error") or "请求失败")
            if "429" in error:
                failures.append(f"{source} 请求频率受限")
            else:
                failures.append(f"{source} 抓取失败")
        return "、".join(failures) if failures else None

    @staticmethod
    def _complete(
        edition_id: UUID,
        article_ids: set[UUID],
        source_results: list[dict[str, object]],
        *,
        analyzed_count: int,
        visible_count: int,
        analysis_failed: int,
        analysis_skipped: int,
        warning_summary: str | None,
    ) -> None:
        with SessionLocal() as session:
            edition = session.get(RadarEdition, edition_id)
            if edition is None:
                return
            edition.article_count = len(article_ids)
            edition.source_results = source_results
            edition.progress = {
                "stage": "complete",
                "completed": visible_count,
                "total": len(article_ids),
                "message": (
                    f"本期抓取 {len(article_ids)} 条，可展示 {visible_count} 条"
                    if visible_count
                    else f"本期抓取 {len(article_ids)} 条，没有内容通过质量筛选"
                ),
                "collected_count": len(article_ids),
                "analyzed_count": analyzed_count,
                "visible_count": visible_count,
                "analysis_failed": analysis_failed,
                "analysis_skipped": analysis_skipped,
            }
            edition.error_summary = warning_summary
            edition.status = RadarEditionStatus.COMPLETE
            edition.finished_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _fail(
        edition_id: UUID,
        source_results: list[dict[str, object]],
        error: str,
        *,
        collected_count: int | None = None,
        analyzed_count: int = 0,
        visible_count: int = 0,
        analysis_failed: int = 0,
        analysis_skipped: int = 0,
    ) -> None:
        with SessionLocal() as session:
            edition = session.get(RadarEdition, edition_id)
            if edition is None:
                return
            edition.status = RadarEditionStatus.FAILED
            edition.finished_at = datetime.now(UTC)
            edition.source_results = source_results
            if collected_count is not None:
                edition.article_count = collected_count
            edition.progress = {
                "stage": "failed",
                "completed": visible_count,
                "total": collected_count or 0,
                "message": error[:500],
                "collected_count": collected_count or 0,
                "analyzed_count": analyzed_count,
                "visible_count": visible_count,
                "analysis_failed": analysis_failed,
                "analysis_skipped": analysis_skipped,
            }
            edition.error_summary = error[:2_000]
            session.commit()

    @staticmethod
    def _set_progress(
        edition_id: UUID,
        *,
        stage: str,
        completed: int,
        total: int,
        message: str,
        current_source: str | None = None,
        source_results: list[dict[str, object]] | None = None,
    ) -> None:
        with SessionLocal() as session:
            edition = session.get(RadarEdition, edition_id)
            if edition is None:
                return
            edition.progress = {
                "stage": stage,
                "completed": completed,
                "total": total,
                "message": message,
                "current_source": current_source,
            }
            if source_results is not None:
                edition.source_results = list(source_results)
            session.commit()
