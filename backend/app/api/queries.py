from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Integer,
    and_,
    case,
    exists,
    func,
    literal_column,
    or_,
    select,
)
from sqlalchemy import (
    cast as sql_cast,
)
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.analysis.schema import OpenSourceStatus, TechnicalCategory
from app.api.cursor import PageCursor
from app.api.schemas import (
    ArticleDetail,
    ArticleSummary,
    AuthorReference,
    SearchResult,
    SourceReference,
    TopicSummary,
)
from app.models import Article, RawItem, Source


@dataclass(frozen=True, slots=True)
class ArticleFilters:
    date_from: date | None = None
    date_to: date | None = None
    source: str | None = None
    category: TechnicalCategory | None = None
    importance_min: float | None = None
    open_source_status: OpenSourceStatus | None = None
    published_from: datetime | None = None
    published_before: datetime | None = None


def article_predicates(filters: ArticleFilters) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = []
    if filters.date_from is not None:
        predicates.append(
            Article.published_at >= datetime.combine(filters.date_from, time.min, tzinfo=UTC)
        )
    if filters.date_to is not None:
        end = datetime.combine(filters.date_to + timedelta(days=1), time.min, tzinfo=UTC)
        predicates.append(Article.published_at < end)
    if filters.published_from is not None:
        predicates.append(Article.published_at >= filters.published_from)
    if filters.published_before is not None:
        predicates.append(Article.published_at < filters.published_before)
    if filters.source:
        predicates.append(
            exists(
                select(1)
                .select_from(RawItem)
                .join(Source, Source.id == RawItem.source_id)
                .where(RawItem.article_id == Article.id, Source.slug == filters.source)
            )
        )
    if filters.category is not None:
        predicates.append(Article.primary_category == filters.category.value)
    if filters.importance_min is not None:
        predicates.append(Article.importance_score >= filters.importance_min)
    if filters.open_source_status is not None:
        predicates.append(Article.open_source_status == filters.open_source_status.value)
    return predicates


def list_articles(
    session: Session,
    filters: ArticleFilters,
    *,
    limit: int,
    cursor: PageCursor | None,
) -> tuple[list[Article], bool]:
    statement = (
        select(Article)
        .options(*_article_load_options())
        .where(*article_predicates(filters))
        .order_by(Article.published_at.desc(), Article.id.desc())
    )
    if cursor is not None:
        statement = statement.where(
            or_(
                Article.published_at < cursor.published_at,
                and_(
                    Article.published_at == cursor.published_at,
                    Article.id < cursor.article_id,
                ),
            )
        )
    articles = list(session.scalars(statement.limit(limit + 1)))
    return articles[:limit], len(articles) > limit


def get_article(session: Session, article_id: UUID) -> Article | None:
    return session.scalar(
        select(Article).options(*_article_load_options()).where(Article.id == article_id)
    )


def search_articles(
    session: Session,
    query_text: str,
    filters: ArticleFilters,
    *,
    limit: int,
    cursor: PageCursor | None,
) -> tuple[list[tuple[Article, int]], bool]:
    regconfig: ColumnElement[str] = literal_column("'simple'::regconfig")
    empty: ColumnElement[str] = literal_column("''")
    space: ColumnElement[str] = literal_column("' '")
    document_text = (
        func.coalesce(Article.title, empty)
        + space
        + func.coalesce(Article.summary, empty)
        + space
        + func.coalesce(Article.content, empty)
    )
    document = func.to_tsvector(regconfig, document_text)
    ts_query = func.websearch_to_tsquery(regconfig, query_text)
    escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    title_match = Article.title.ilike(pattern, escape="\\")
    summary_match = Article.summary.ilike(pattern, escape="\\")
    content_match = Article.content.ilike(pattern, escape="\\")
    full_text_match = document.op("@@")(ts_query)
    rank_key = sql_cast(func.ts_rank_cd(document, ts_query) * 1_000_000, Integer)
    fallback_key = case(
        (title_match, 500_000),
        (summary_match, 100_000),
        else_=10_000,
    )
    score_key = func.greatest(rank_key, fallback_key)
    search_match = (
        or_(full_text_match, title_match, summary_match, content_match)
        if _contains_cjk(query_text)
        else full_text_match
    )
    predicates = [*article_predicates(filters), search_match]
    statement = (
        select(Article, score_key.label("search_score_key"))
        .options(*_article_load_options())
        .where(*predicates)
        .order_by(score_key.desc(), Article.published_at.desc(), Article.id.desc())
    )
    if cursor is not None:
        if cursor.score_key is None:
            raise ValueError("search cursor is missing score")
        statement = statement.where(
            or_(
                score_key < cursor.score_key,
                and_(
                    score_key == cursor.score_key,
                    Article.published_at < cursor.published_at,
                ),
                and_(
                    score_key == cursor.score_key,
                    Article.published_at == cursor.published_at,
                    Article.id < cursor.article_id,
                ),
            )
        )
    rows = [(row[0], int(row[1])) for row in session.execute(statement.limit(limit + 1))]
    return rows[:limit], len(rows) > limit


def topic_summaries(session: Session, filters: ArticleFilters) -> list[TopicSummary]:
    statement = (
        select(
            Article.primary_category,
            func.count(Article.id),
            func.avg(Article.importance_score),
            func.max(Article.published_at),
        )
        .where(Article.primary_category.is_not(None), *article_predicates(filters))
        .group_by(Article.primary_category)
        .order_by(func.count(Article.id).desc(), Article.primary_category)
    )
    return [
        TopicSummary(
            category=TechnicalCategory(category),
            article_count=count,
            average_importance=round(float(average), 2) if average is not None else None,
            latest_published_at=latest,
        )
        for category, count, average, latest in session.execute(statement)
    ]


def count_articles(session: Session, filters: ArticleFilters) -> int:
    return session.scalar(select(func.count(Article.id)).where(*article_predicates(filters))) or 0


def highest_importance_articles(
    session: Session, filters: ArticleFilters, *, limit: int
) -> list[Article]:
    return list(
        session.scalars(
            select(Article)
            .options(*_article_load_options())
            .where(*article_predicates(filters))
            .order_by(
                Article.importance_score.desc().nulls_last(),
                Article.published_at.desc(),
                Article.id.desc(),
            )
            .limit(limit)
        )
    )


def article_summary(article: Article) -> ArticleSummary:
    return ArticleSummary(
        id=article.id,
        kind=article.kind,
        canonical_url=article.canonical_url,
        title=article.title,
        summary=article.summary,
        primary_category=(
            TechnicalCategory(article.primary_category) if article.primary_category else None
        ),
        tags=article.analysis_tags,
        importance_score=article.importance_score,
        credibility_score=article.credibility_score,
        open_source_status=(
            OpenSourceStatus(article.open_source_status) if article.open_source_status else None
        ),
        published_at=article.published_at,
        event_cluster_id=article.event_cluster_id,
        sources=_source_references(article),
        authors=[
            AuthorReference(name=author.name, url=author.url)
            for author in sorted(article.authors, key=lambda value: value.name.casefold())
        ],
    )


def article_detail(article: Article) -> ArticleDetail:
    summary = article_summary(article)
    return ArticleDetail(
        **summary.model_dump(),
        content=article.content,
        license=article.license,
        analysis=article.analysis,
        analysis_schema_version=article.analysis_schema_version,
        analyzed_at=article.analyzed_at,
        source_tags=sorted(tag.name for tag in article.tags),
    )


def search_result(article: Article, score_key: int) -> SearchResult:
    summary = article_summary(article)
    return SearchResult(**summary.model_dump(), search_score=round(score_key / 1_000_000, 6))


def _article_load_options() -> tuple[ExecutableOption, ...]:
    return (
        selectinload(Article.raw_items).selectinload(RawItem.source),
        selectinload(Article.authors),
        selectinload(Article.tags),
    )


def _source_references(article: Article) -> list[SourceReference]:
    references: list[SourceReference] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in sorted(article.raw_items, key=lambda item: (item.source.slug, item.url)):
        key = (raw_item.source.slug, raw_item.url)
        if key in seen:
            continue
        references.append(
            SourceReference(
                slug=raw_item.source.slug,
                name=raw_item.source.name,
                item_url=raw_item.url,
            )
        )
        seen.add(key)
    return references


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)
