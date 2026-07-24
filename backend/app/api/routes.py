from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select

from app.analysis import AnalysisConfig, AnalysisPipeline
from app.analysis.provider import ProviderError
from app.analysis.schema import OpenSourceStatus, TechnicalCategory
from app.api.cursor import PageCursor, decode_cursor, encode_cursor
from app.api.dependencies import SessionDependency
from app.api.queries import (
    ArticleFilters,
    article_detail,
    article_summary,
    count_articles,
    get_article,
    highest_importance_articles,
    list_articles,
    search_articles,
    search_result,
    topic_summaries,
)
from app.api.schemas import (
    AnalysisJobStatus,
    ArticleDetail,
    ArticlePage,
    CleanupReportResponse,
    DailyBrief,
    PageMetadata,
    RadarEditionList,
    RadarEditionSummary,
    SearchPage,
    TopicList,
    WritingDraftRequest,
    WritingDraftUpdate,
    WritingProjectResponse,
)
from app.config import get_settings
from app.db import SessionLocal
from app.domain import AnalysisRunStatus
from app.editions import ManualRadarService
from app.maintenance import RetentionCleanupService
from app.models import AnalysisRun, RadarEdition, WritingProject
from app.writing import WritingConfig, WritingService

router = APIRouter()

DateFilter = Annotated[date | None, Query(description="Inclusive publication date (YYYY-MM-DD)")]
SourceFilter = Annotated[str | None, Query(min_length=1, max_length=100)]
ImportanceFilter = Annotated[float | None, Query(ge=0, le=10)]
CursorFilter = Annotated[str | None, Query(min_length=1, max_length=500)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.get("/articles", response_model=ArticlePage, tags=["articles"])
def articles(
    session: SessionDependency,
    edition: UUID | None = None,
    date_from: DateFilter = None,
    date_to: DateFilter = None,
    source: SourceFilter = None,
    category: TechnicalCategory | None = None,
    importance_min: ImportanceFilter = None,
    open_source_status: OpenSourceStatus | None = None,
    cursor: CursorFilter = None,
    limit: PageLimit = 20,
) -> ArticlePage:
    filters = _filters(
        date_from,
        date_to,
        source,
        category,
        importance_min,
        open_source_status,
        edition,
    )
    decoded_cursor = _decode_cursor(cursor)
    started = perf_counter()
    rows, has_more = list_articles(session, filters, limit=limit, cursor=decoded_cursor)
    items = [article_summary(article) for article in rows]
    query_ms = _elapsed_ms(started)
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(PageCursor(published_at=last.published_at, article_id=last.id))
    return ArticlePage(
        items=items,
        page=PageMetadata(
            limit=limit,
            has_more=has_more,
            next_cursor=next_cursor,
            query_ms=query_ms,
        ),
    )


@router.get("/radar-editions", response_model=RadarEditionList, tags=["radar"])
def radar_editions(session: SessionDependency) -> RadarEditionList:
    rows = list(
        session.scalars(select(RadarEdition).order_by(RadarEdition.captured_at.desc()).limit(100))
    )
    return RadarEditionList(items=[_edition_summary(row) for row in rows])


@router.post(
    "/radar-editions",
    response_model=RadarEditionSummary,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["radar"],
)
def create_radar_edition(background_tasks: BackgroundTasks) -> RadarEditionSummary:
    service = ManualRadarService()
    edition_id = service.create()
    background_tasks.add_task(service.run, edition_id)
    with SessionLocal() as session:
        edition = session.get(RadarEdition, edition_id)
        if edition is None:
            raise HTTPException(status_code=500, detail="failed to create radar edition")
        return _edition_summary(edition)


@router.get(
    "/radar-editions/{edition_id}", response_model=RadarEditionSummary, tags=["radar"]
)
def radar_edition(edition_id: UUID, session: SessionDependency) -> RadarEditionSummary:
    edition = session.get(RadarEdition, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="radar edition not found")
    return _edition_summary(edition)


@router.get(
    "/maintenance/cleanup-preview",
    response_model=CleanupReportResponse,
    tags=["maintenance"],
)
def cleanup_preview(
    session: SessionDependency,
    keep_editions: Annotated[int, Query(ge=1, le=50)] = 10,
) -> CleanupReportResponse:
    report = RetentionCleanupService().preview(session, keep_editions=keep_editions)
    return CleanupReportResponse.model_validate(report.as_dict())


@router.delete(
    "/maintenance/data",
    response_model=CleanupReportResponse,
    tags=["maintenance"],
)
def cleanup_data(
    session: SessionDependency,
    keep_editions: Annotated[int, Query(ge=1, le=50)] = 10,
) -> CleanupReportResponse:
    try:
        report = RetentionCleanupService().run(session, keep_editions=keep_editions)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CleanupReportResponse.model_validate(report.as_dict())


@router.get("/articles/{article_id}", response_model=ArticleDetail, tags=["articles"])
def article_by_id(article_id: UUID, session: SessionDependency) -> ArticleDetail:
    article = get_article(session, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    return article_detail(article)


@router.post(
    "/articles/{article_id}/writing-project",
    response_model=WritingProjectResponse,
    tags=["writing"],
)
def create_writing_project(
    article_id: UUID, session: SessionDependency
) -> WritingProjectResponse:
    try:
        project = WritingService.get_or_create(session, article_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _writing_project_response(project)


@router.get(
    "/writing-projects/{project_id}",
    response_model=WritingProjectResponse,
    tags=["writing"],
)
def writing_project(project_id: UUID, session: SessionDependency) -> WritingProjectResponse:
    try:
        project = WritingService.get(session, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _writing_project_response(project)


@router.patch(
    "/writing-projects/{project_id}",
    response_model=WritingProjectResponse,
    tags=["writing"],
)
def update_writing_draft(
    project_id: UUID,
    request: WritingDraftUpdate,
    session: SessionDependency,
) -> WritingProjectResponse:
    try:
        project = WritingService.save_draft(session, project_id, request.draft_content)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _writing_project_response(project)


@router.post(
    "/writing-projects/{project_id}/angles",
    response_model=WritingProjectResponse,
    tags=["writing"],
)
async def generate_writing_angles(
    project_id: UUID, session: SessionDependency
) -> WritingProjectResponse:
    service = _writing_service()
    try:
        project = await service.generate_angles(session, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ProviderError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"角度生成失败：{exc}") from exc
    return _writing_project_response(project)


@router.post(
    "/writing-projects/{project_id}/draft",
    response_model=WritingProjectResponse,
    tags=["writing"],
)
async def generate_writing_draft(
    project_id: UUID,
    request: WritingDraftRequest,
    session: SessionDependency,
) -> WritingProjectResponse:
    service = _writing_service()
    try:
        project = await service.generate_draft(
            session,
            project_id,
            angle_id=request.angle_id,
            output_format=request.output_format,
            human_input=request.human_input,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"正文生成失败：{exc}") from exc
    return _writing_project_response(project)


@router.post(
    "/writing-projects/{project_id}/review",
    response_model=WritingProjectResponse,
    tags=["writing"],
)
async def review_writing_draft(
    project_id: UUID, session: SessionDependency
) -> WritingProjectResponse:
    service = _writing_service()
    try:
        project = await service.review_draft(session, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=f"审校失败：{exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"审校失败：{exc}") from exc
    return _writing_project_response(project)


@router.post(
    "/articles/{article_id}/deep-analysis",
    response_model=AnalysisJobStatus,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["articles"],
)
async def generate_deep_analysis(
    article_id: UUID,
    session: SessionDependency,
    background_tasks: BackgroundTasks,
) -> AnalysisJobStatus:
    article = get_article(session, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    current = _analysis_job_status(session, article_id, article.analysis)
    if current.status in {"complete", "running"}:
        return current
    background_tasks.add_task(_run_deep_analysis, article_id)
    return AnalysisJobStatus(
        article_id=article_id,
        status="queued",
        analysis_depth="brief",
    )


@router.get(
    "/articles/{article_id}/analysis-status",
    response_model=AnalysisJobStatus,
    tags=["articles"],
)
def analysis_status(article_id: UUID, session: SessionDependency) -> AnalysisJobStatus:
    article = get_article(session, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    return _analysis_job_status(session, article_id, article.analysis)


async def _run_deep_analysis(article_id: UUID) -> None:
    try:
        await AnalysisPipeline(AnalysisConfig.from_file(), depth="deep").run_article(article_id)
    except (ValueError, LookupError):
        return


def _analysis_job_status(
    session: SessionDependency,
    article_id: UUID,
    analysis: dict[str, object],
) -> AnalysisJobStatus:
    if analysis.get("depth") == "deep":
        return AnalysisJobStatus(
            article_id=article_id,
            status="complete",
            analysis_depth="deep",
        )
    latest = session.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.article_id == article_id,
            AnalysisRun.prompt_version.endswith("-deep"),
        )
        .order_by(AnalysisRun.started_at.desc())
        .limit(1)
    )
    if latest is None:
        job_status = "idle"
    elif latest.status is AnalysisRunStatus.RUNNING:
        job_status = "running"
    elif latest.status is AnalysisRunStatus.FAILED:
        job_status = "failed"
    else:
        job_status = "idle"
    return AnalysisJobStatus(
        article_id=article_id,
        status=job_status,
        analysis_depth="brief",
    )


@router.get("/topics", response_model=TopicList, tags=["topics"])
def topics(
    session: SessionDependency,
    edition: UUID | None = None,
    date_from: DateFilter = None,
    date_to: DateFilter = None,
    source: SourceFilter = None,
    importance_min: ImportanceFilter = None,
    open_source_status: OpenSourceStatus | None = None,
) -> TopicList:
    filters = _filters(
        date_from,
        date_to,
        source,
        None,
        importance_min,
        open_source_status,
        edition,
    )
    started = perf_counter()
    items = topic_summaries(session, filters)
    return TopicList(items=items, query_ms=_elapsed_ms(started))


@router.get("/daily-brief", response_model=DailyBrief, tags=["briefs"])
def daily_brief(
    session: SessionDependency,
    day: Annotated[date | None, Query(alias="date")] = None,
    source: SourceFilter = None,
    category: TechnicalCategory | None = None,
    importance_min: ImportanceFilter = None,
    open_source_status: OpenSourceStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> DailyBrief:
    timezone_name = get_settings().brief_timezone
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=500, detail="invalid brief timezone") from exc
    brief_day = day or datetime.now(timezone).date()
    local_start = datetime.combine(brief_day, time.min, tzinfo=timezone)
    local_end = local_start + timedelta(days=1)
    filters = ArticleFilters(
        source=source,
        category=category,
        importance_min=importance_min,
        open_source_status=open_source_status,
        published_from=local_start.astimezone(UTC),
        published_before=local_end.astimezone(UTC),
    )
    started = perf_counter()
    total = count_articles(session, filters)
    topic_items = topic_summaries(session, filters)
    rows = highest_importance_articles(session, filters, limit=limit)
    top_articles = [article_summary(article) for article in rows]
    return DailyBrief(
        date=brief_day,
        timezone=timezone_name,
        total_articles=total,
        topics=topic_items,
        top_articles=top_articles,
        query_ms=_elapsed_ms(started),
    )


@router.get("/search", response_model=SearchPage, tags=["search"])
def search(
    session: SessionDependency,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    date_from: DateFilter = None,
    date_to: DateFilter = None,
    source: SourceFilter = None,
    category: TechnicalCategory | None = None,
    importance_min: ImportanceFilter = None,
    open_source_status: OpenSourceStatus | None = None,
    cursor: CursorFilter = None,
    limit: PageLimit = 20,
) -> SearchPage:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="query must contain at least 2 characters")
    filters = _filters(date_from, date_to, source, category, importance_min, open_source_status)
    decoded_cursor = _decode_cursor(cursor)
    started = perf_counter()
    try:
        rows, has_more = search_articles(
            session,
            query,
            filters,
            limit=limit,
            cursor=decoded_cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = [search_result(article, score_key) for article, score_key in rows]
    query_ms = _elapsed_ms(started)
    next_cursor = None
    if has_more and rows:
        last, score_key = rows[-1]
        next_cursor = encode_cursor(
            PageCursor(
                published_at=last.published_at,
                article_id=last.id,
                score_key=score_key,
            )
        )
    return SearchPage(
        query=query,
        items=items,
        page=PageMetadata(
            limit=limit,
            has_more=has_more,
            next_cursor=next_cursor,
            query_ms=query_ms,
        ),
    )


def _filters(
    date_from: date | None,
    date_to: date | None,
    source: str | None,
    category: TechnicalCategory | None,
    importance_min: float | None,
    open_source_status: OpenSourceStatus | None,
    edition_id: UUID | None = None,
) -> ArticleFilters:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    return ArticleFilters(
        edition_id=edition_id,
        date_from=date_from,
        date_to=date_to,
        source=source,
        category=category,
        importance_min=importance_min,
        open_source_status=open_source_status,
    )


def _edition_summary(edition: RadarEdition) -> RadarEditionSummary:
    return RadarEditionSummary(
        id=edition.id,
        captured_at=edition.captured_at,
        finished_at=edition.finished_at,
        status=edition.status,
        article_count=edition.article_count,
        source_results=edition.source_results,
        progress=edition.progress,
        error_summary=edition.error_summary,
    )


def _writing_service() -> WritingService:
    try:
        return WritingService(WritingConfig.from_file())
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"写作模型不可用：{exc}") from exc


def _writing_project_response(project: WritingProject) -> WritingProjectResponse:
    return WritingProjectResponse.model_validate(
        {
            "id": project.id,
            "article_id": project.article_id,
            "status": project.status,
            "angle_options": project.angle_options,
            "selected_angle_id": project.selected_angle_id,
            "output_format": project.output_format,
            "human_input": project.human_input or {},
            "draft_content": project.draft_content,
            "review": project.review or None,
            "provider": project.provider,
            "model": project.model,
            "prompt_version": project.prompt_version,
            "error_summary": project.error_summary,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
    )


def _decode_cursor(value: str | None) -> PageCursor | None:
    if value is None:
        return None
    try:
        return decode_cursor(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)
