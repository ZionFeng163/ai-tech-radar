from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

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
    ArticleDetail,
    ArticlePage,
    DailyBrief,
    PageMetadata,
    SearchPage,
    TopicList,
)
from app.config import get_settings

router = APIRouter()

DateFilter = Annotated[date | None, Query(description="Inclusive publication date (YYYY-MM-DD)")]
SourceFilter = Annotated[str | None, Query(min_length=1, max_length=100)]
ImportanceFilter = Annotated[float | None, Query(ge=0, le=10)]
CursorFilter = Annotated[str | None, Query(min_length=1, max_length=500)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.get("/articles", response_model=ArticlePage, tags=["articles"])
def articles(
    session: SessionDependency,
    date_from: DateFilter = None,
    date_to: DateFilter = None,
    source: SourceFilter = None,
    category: TechnicalCategory | None = None,
    importance_min: ImportanceFilter = None,
    open_source_status: OpenSourceStatus | None = None,
    cursor: CursorFilter = None,
    limit: PageLimit = 20,
) -> ArticlePage:
    filters = _filters(date_from, date_to, source, category, importance_min, open_source_status)
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


@router.get("/articles/{article_id}", response_model=ArticleDetail, tags=["articles"])
def article_by_id(article_id: UUID, session: SessionDependency) -> ArticleDetail:
    article = get_article(session, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    return article_detail(article)


@router.get("/topics", response_model=TopicList, tags=["topics"])
def topics(
    session: SessionDependency,
    date_from: DateFilter = None,
    date_to: DateFilter = None,
    source: SourceFilter = None,
    importance_min: ImportanceFilter = None,
    open_source_status: OpenSourceStatus | None = None,
) -> TopicList:
    filters = _filters(date_from, date_to, source, None, importance_min, open_source_status)
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
) -> ArticleFilters:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    return ArticleFilters(
        date_from=date_from,
        date_to=date_to,
        source=source,
        category=category,
        importance_min=importance_min,
        open_source_status=open_source_status,
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
