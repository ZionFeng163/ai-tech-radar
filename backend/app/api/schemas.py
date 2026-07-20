from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.schema import OpenSourceStatus, TechnicalCategory
from app.domain import ArticleKind


class SourceReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    item_url: str


class AuthorReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    url: str | None


class ArticleSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: ArticleKind
    canonical_url: str | None
    title: str
    summary: str | None
    primary_category: TechnicalCategory | None
    tags: list[str]
    importance_score: float | None
    credibility_score: float | None
    open_source_status: OpenSourceStatus | None
    published_at: datetime
    event_cluster_id: UUID | None
    sources: list[SourceReference]
    authors: list[AuthorReference]


class ArticleDetail(ArticleSummary):
    content: str | None
    license: str | None
    analysis: dict[str, object]
    analysis_schema_version: str | None
    analyzed_at: datetime | None
    source_tags: list[str]


class PageMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int
    has_more: bool
    next_cursor: str | None
    query_ms: float = Field(ge=0)


class ArticlePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ArticleSummary]
    page: PageMetadata


class SearchResult(ArticleSummary):
    search_score: float = Field(ge=0)


class SearchPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    items: list[SearchResult]
    page: PageMetadata


class TopicSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: TechnicalCategory
    article_count: int = Field(ge=0)
    average_importance: float | None
    latest_published_at: datetime


class TopicList(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TopicSummary]
    query_ms: float = Field(ge=0)


class DailyBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    timezone: str
    total_articles: int = Field(ge=0)
    topics: list[TopicSummary]
    top_articles: list[ArticleSummary]
    query_ms: float = Field(ge=0)
