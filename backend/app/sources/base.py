from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Self

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from app.domain import ArticleKind, SourceKind


def utc_now() -> datetime:
    return datetime.now(UTC)


class AdapterCursor(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: dict[str, JsonValue] = Field(default_factory=dict)


class SourceDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=255)
    kind: SourceKind
    base_url: AnyHttpUrl | None = None


class CollectedItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_id: str = Field(min_length=1, max_length=500)
    url: AnyHttpUrl
    payload: dict[str, JsonValue]
    fetched_at: AwareDatetime = Field(default_factory=utc_now)

    def deduplication_key(self, source_slug: str) -> str:
        return f"{source_slug}:{self.external_id}"


class AuthorData(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=500)
    url: AnyHttpUrl | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)


class NormalizedItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_id: str = Field(min_length=1, max_length=500)
    kind: ArticleKind
    canonical_url: AnyHttpUrl
    title: str = Field(min_length=1)
    content: str | None = None
    published_at: AwareDatetime
    updated_at: AwareDatetime | None = None
    authors: list[AuthorData] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    license: str | None = Field(default=None, max_length=255)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class FetchBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CollectedItem]
    next_cursor: AdapterCursor
    has_more: bool = False

    @model_validator(mode="after")
    def require_progress_for_more_items(self) -> Self:
        if self.has_more and not self.items:
            raise ValueError("a batch with has_more=true must contain at least one item")
        return self


class SourceAdapter(ABC):
    descriptor: SourceDescriptor

    @abstractmethod
    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        """Fetch one page without writing to the database."""

    @abstractmethod
    def normalize(self, item: CollectedItem) -> NormalizedItem:
        """Convert a provider payload into the shared article contract."""

    def deduplication_key(self, item: CollectedItem) -> str:
        return item.deduplication_key(self.descriptor.slug)

    async def aclose(self) -> None:
        """Release adapter resources when a concrete adapter owns any."""
        return None

    async def __aenter__(self) -> "SourceAdapter":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()
