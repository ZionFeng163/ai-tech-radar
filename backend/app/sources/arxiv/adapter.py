import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
from pydantic import AnyHttpUrl, JsonValue

from app.domain import ArticleKind, SourceKind
from app.sources.arxiv.config import ArxivConfig
from app.sources.arxiv.parser import parse_datetime, parse_feed
from app.sources.base import (
    AdapterCursor,
    AuthorData,
    CollectedItem,
    FetchBatch,
    NormalizedItem,
    SourceAdapter,
    SourceDescriptor,
)

Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_query_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d%H%M")


def _quote_keyword(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'all:"{escaped}"'


class ArxivAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        slug="arxiv",
        name="arXiv",
        kind=SourceKind.ARXIV,
        base_url=AnyHttpUrl("https://arxiv.org"),
    )

    def __init__(
        self,
        config: ArxivConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Clock = _utc_now,
        monotonic: MonotonicClock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self.config = config or ArxivConfig()
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._client = client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._last_request_at: float | None = None

    async def __aenter__(self) -> "ArxivAdapter":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def build_search_query(self, window_start: datetime, window_end: datetime) -> str:
        filters: list[str] = []
        if self.config.categories:
            categories = " OR ".join(f"cat:{value}" for value in self.config.categories)
            filters.append(f"({categories})")
        if self.config.keywords:
            keywords = " OR ".join(_quote_keyword(value) for value in self.config.keywords)
            filters.append(f"({keywords})")
        filters.append(
            "submittedDate:"
            f"[{_format_query_time(window_start)} TO {_format_query_time(window_end)}]"
        )
        return " AND ".join(filters)

    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        window_start, window_end, offset = self._resolve_cursor(cursor)
        page_size = min(limit, self.config.page_size)
        response = await self._request(
            {
                "search_query": self.build_search_query(window_start, window_end),
                "start": offset,
                "max_results": page_size,
                "sortBy": "submittedDate",
                "sortOrder": "ascending",
            }
        )
        feed = parse_feed(response.content)
        if not feed.entries and offset < feed.total_results:
            raise RuntimeError("arXiv returned an empty page before the reported result total")
        fetched_at = self._clock()
        items = [
            CollectedItem(
                external_id=self._required_string(payload, "external_id"),
                url=AnyHttpUrl(self._required_string(payload, "detail_url")),
                payload=payload,
                fetched_at=fetched_at,
            )
            for payload in feed.entries
        ]
        next_offset = offset + len(items)
        has_more = bool(items) and next_offset < feed.total_results
        if has_more:
            next_value: dict[str, JsonValue] = {
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "offset": next_offset,
            }
        else:
            next_value = {"watermark": window_end.isoformat()}

        return FetchBatch(
            items=items,
            next_cursor=AdapterCursor(value=next_value),
            has_more=has_more,
        )

    def normalize(self, item: CollectedItem) -> NormalizedItem:
        payload = item.payload
        authors_value = payload.get("authors", [])
        categories_value = payload.get("categories", [])
        authors = [
            AuthorData(name=cast(str, author["name"]))
            for author in cast(list[dict[str, JsonValue]], authors_value)
            if isinstance(author, dict) and isinstance(author.get("name"), str)
        ]
        categories = [
            value for value in cast(list[JsonValue], categories_value) if isinstance(value, str)
        ]
        published = self._required_string(payload, "published")
        updated = payload.get("updated")
        license_value = payload.get("license")

        metadata: dict[str, JsonValue] = {
            "provider": "arxiv",
            "versioned_id": payload.get("versioned_id"),
            "version": payload.get("version"),
            "published_at": payload.get("published"),
            "updated_at": payload.get("updated"),
            "pdf_url": payload.get("pdf_url"),
            "detail_url": payload.get("detail_url"),
            "primary_category": payload.get("primary_category"),
            "categories": cast(list[JsonValue], categories),
            "doi": payload.get("doi"),
            "journal_ref": payload.get("journal_ref"),
            "comment": payload.get("comment"),
        }
        return NormalizedItem(
            external_id=item.external_id,
            kind=ArticleKind.PAPER,
            canonical_url=item.url,
            title=self._required_string(payload, "title"),
            content=self._optional_string(payload, "summary"),
            published_at=parse_datetime(published),
            updated_at=parse_datetime(updated) if isinstance(updated, str) else None,
            authors=authors,
            tags=categories,
            license=license_value if isinstance(license_value, str) else None,
            metadata=metadata,
        )

    def _resolve_cursor(self, cursor: AdapterCursor | None) -> tuple[datetime, datetime, int]:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        now = now.astimezone(UTC)
        value = cursor.value if cursor else {}

        window_start_value = value.get("window_start")
        window_end_value = value.get("window_end")
        if isinstance(window_start_value, str) and isinstance(window_end_value, str):
            window_start = parse_datetime(window_start_value)
            window_end = parse_datetime(window_end_value)
            offset_value = value.get("offset", 0)
            if (
                not isinstance(offset_value, int)
                or isinstance(offset_value, bool)
                or offset_value < 0
            ):
                raise ValueError("cursor offset must be a non-negative integer")
            return window_start, window_end, offset_value

        watermark_value = value.get("watermark")
        if watermark_value is not None and not isinstance(watermark_value, str):
            raise ValueError("cursor watermark must be an ISO-8601 string")
        if isinstance(watermark_value, str):
            watermark = parse_datetime(watermark_value).astimezone(UTC)
            window_start = watermark - timedelta(minutes=self.config.overlap_minutes)
        else:
            window_start = now - timedelta(hours=self.config.window_hours)
        return window_start, now, 0

    async def _request(self, params: dict[str, str | int]) -> httpx.Response:
        for attempt in range(self.config.max_retries + 1):
            await self._respect_rate_limit()
            try:
                response = await self._client.get(str(self.config.api_url), params=params)
            except httpx.TransportError:
                if attempt >= self.config.max_retries:
                    raise
                await self._sleep(self.config.retry_backoff_seconds * (2**attempt))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.config.max_retries:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else None
                except ValueError:
                    delay = None
                await self._sleep(
                    delay if delay is not None else self.config.retry_backoff_seconds * (2**attempt)
                )
                continue

            response.raise_for_status()
            return response

        raise RuntimeError("arXiv request retry loop exited unexpectedly")

    async def _respect_rate_limit(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.config.request_interval_seconds - elapsed
            if remaining > 0:
                await self._sleep(remaining)
        self._last_request_at = self._monotonic()

    @staticmethod
    def _required_string(payload: dict[str, JsonValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"arXiv payload field {key!r} must be a non-empty string")
        return value

    @staticmethod
    def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) else None
