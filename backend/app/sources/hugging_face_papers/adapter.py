import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from pydantic import AnyHttpUrl, JsonValue, TypeAdapter

from app.domain import ArticleKind, SourceKind
from app.sources.base import (
    AdapterCursor,
    AuthorData,
    CollectedItem,
    FetchBatch,
    NormalizedItem,
    SourceAdapter,
    SourceDescriptor,
)
from app.sources.hugging_face_papers.config import HuggingFacePapersConfig

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
JSON_OBJECTS = TypeAdapter(list[dict[str, JsonValue]])


def _utc_now() -> datetime:
    return datetime.now(UTC)


class HuggingFacePapersAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        slug="hugging-face-papers",
        name="Hugging Face Daily Papers",
        kind=SourceKind.HUGGING_FACE,
        base_url=AnyHttpUrl("https://huggingface.co/papers"),
    )

    def __init__(
        self,
        config: HuggingFacePapersConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Clock = _utc_now,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self.config = config or HuggingFacePapersConfig()
        self._clock = clock
        self._sleep = sleep
        headers = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }
        if self.config.token is not None:
            headers["Authorization"] = f"Bearer {self.config.token.get_secret_value()}"
        self._client = client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers=headers,
            follow_redirects=True,
        )
        self._owns_client = client is None

    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        now = self._aware_now()
        previous_watermark = self._cursor_watermark(cursor)
        cutoff = previous_watermark - timedelta(seconds=self.config.overlap_seconds)
        response = await self._request(
            f"{self.config.endpoint}api/daily_papers",
            params={"limit": min(max(limit, 20), self.config.page_size)},
        )
        values = JSON_OBJECTS.validate_python(response.json())
        candidates: list[tuple[int, datetime, CollectedItem]] = []
        maximum = previous_watermark
        for value in values:
            paper = self._required_object(value, "paper")
            submitted_value = (
                self._optional_string(paper, "submittedOnDailyAt")
                or self._optional_string(value, "publishedAt")
                or self._required_string(paper, "publishedAt")
            )
            submitted_at = self._parse_datetime(submitted_value)
            maximum = max(maximum, submitted_at)
            if submitted_at < cutoff:
                continue
            paper_id = self._required_string(paper, "id")
            payload = dict(paper)
            payload["_daily_paper"] = {
                "publishedAt": value.get("publishedAt"),
                "title": value.get("title"),
                "upvotes": value.get("upvotes"),
            }
            upvotes = self._integer(paper.get("upvotes"))
            candidates.append(
                (
                    upvotes,
                    submitted_at,
                    CollectedItem(
                        external_id=f"paper:{paper_id}",
                        url=AnyHttpUrl(
                            f"{self.config.endpoint}papers/{quote(paper_id, safe='.')}"
                        ),
                        payload=payload,
                        fetched_at=now,
                    ),
                )
            )
        candidates.sort(key=lambda value: (value[0], value[1]), reverse=True)
        items = [value[2] for value in candidates[:limit]]
        return FetchBatch(
            items=items,
            next_cursor=AdapterCursor(
                value={
                    "watermark": maximum.isoformat(),
                    "snapshot_at": now.isoformat(),
                }
            ),
            has_more=False,
        )

    def normalize(self, item: CollectedItem) -> NormalizedItem:
        payload = item.payload
        paper_id = self._required_string(payload, "id")
        title = self._required_string(payload, "title")
        summary = self._optional_string(payload, "summary")
        published_value = self._required_string(payload, "publishedAt")
        submitted_value = (
            self._optional_string(payload, "submittedOnDailyAt") or published_value
        )
        author_values = payload.get("authors", [])
        authors: list[AuthorData] = []
        if isinstance(author_values, list):
            for author in author_values:
                if not isinstance(author, dict):
                    continue
                name = author.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                author_id = author.get("_id")
                authors.append(
                    AuthorData(
                        name=name.strip(),
                        external_ids=(
                            {"hugging_face_author_id": author_id}
                            if isinstance(author_id, str)
                            else {}
                        ),
                    )
                )
        organization = payload.get("organization")
        organization_value = organization if isinstance(organization, dict) else None
        metadata: dict[str, JsonValue] = {
            "provider": "hugging_face_papers",
            "resource_type": "paper",
            "arxiv_id": paper_id,
            "paper_published_at": published_value,
            "submitted_on_daily_at": submitted_value,
            "upvotes": payload.get("upvotes"),
            "discussion_id": payload.get("discussionId"),
            "project_page": payload.get("projectPage"),
            "github_repo": payload.get("githubRepo"),
            "organization": organization_value,
        }
        tags = ["Hugging Face Daily Papers", "论文精选"]
        if organization_value:
            name = organization_value.get("name")
            if isinstance(name, str) and name:
                tags.append(name)
        return NormalizedItem(
            external_id=item.external_id,
            kind=ArticleKind.PAPER,
            canonical_url=item.url,
            title=title,
            content=summary,
            published_at=self._parse_datetime(submitted_value),
            updated_at=self._parse_datetime(submitted_value),
            authors=authors,
            tags=tags,
            metadata=metadata,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        url: str,
        *,
        params: dict[str, int],
    ) -> httpx.Response:
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._client.get(url, params=params)
            except httpx.TransportError:
                if attempt >= self.config.max_retries:
                    raise
                await self._sleep(self.config.retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.config.max_retries:
                    response.raise_for_status()
                retry_after = response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after is not None else None
                except ValueError:
                    delay = None
                await self._sleep(
                    delay
                    if delay is not None
                    else self.config.retry_backoff_seconds * (2**attempt)
                )
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("Hugging Face Daily Papers request retry loop exited unexpectedly")

    def _cursor_watermark(self, cursor: AdapterCursor | None) -> datetime:
        if cursor is not None:
            value = cursor.value.get("watermark")
            if isinstance(value, str):
                return self._parse_datetime(value)
        return self._aware_now() - timedelta(hours=self.config.initial_window_hours)

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Hugging Face paper timestamp must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _required_object(
        payload: dict[str, JsonValue], key: str
    ) -> dict[str, JsonValue]:
        value = payload.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"Hugging Face Daily Papers field {key!r} must be an object")
        return value

    @staticmethod
    def _required_string(payload: dict[str, JsonValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Hugging Face Daily Papers field {key!r} must be a non-empty string"
            )
        return value.strip()

    @staticmethod
    def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _integer(value: JsonValue | None) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
