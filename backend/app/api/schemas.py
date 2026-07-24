from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.schema import OpenSourceStatus, SignalType, TechnicalCategory
from app.domain import ArticleKind, RadarEditionStatus


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
    heat_score: float | None
    signal_type: SignalType | None
    technical_overview: str | None
    novelty_summary: str | None
    heat_reasons: list[str]
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
    analysis_depth: Literal["brief", "deep"]


class AnalysisJobStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_id: UUID
    status: Literal["idle", "queued", "running", "complete", "failed"]
    analysis_depth: Literal["brief", "deep"]


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


class RadarEditionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    captured_at: datetime
    finished_at: datetime | None
    status: RadarEditionStatus
    article_count: int = Field(ge=0)
    source_results: list[dict[str, object]]
    progress: dict[str, object]
    error_summary: str | None


class RadarEditionList(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RadarEditionSummary]


class CleanupReportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    keep_editions: int = Field(ge=1, le=50)
    keep_fetch_runs_per_source: int = Field(ge=1)
    keep_analysis_runs_per_article: int = Field(ge=1)
    blocked: bool
    running_editions: int = Field(ge=0)
    running_fetch_runs: int = Field(ge=0)
    running_analysis_runs: int = Field(ge=0)
    editions: int = Field(ge=0)
    articles: int = Field(ge=0)
    raw_items: int = Field(ge=0)
    fetch_runs: int = Field(ge=0)
    analysis_runs: int = Field(ge=0)
    authors: int = Field(ge=0)
    tags: int = Field(ge=0)
    event_clusters: int = Field(ge=0)


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
