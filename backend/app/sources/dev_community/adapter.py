from datetime import datetime
from typing import cast

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

JSON_OBJECTS = TypeAdapter(list[dict[str, JsonValue]])


class DevCommunityAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        slug="dev-community",
        name="DEV Community",
        kind=SourceKind.BLOG,
        base_url=AnyHttpUrl("https://dev.to"),
    )

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "AI-Tech-Radar/0.1"},
            follow_redirects=True,
        )
        self._owns_client = client is None

    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        del cursor
        if limit < 1:
            raise ValueError("limit must be at least 1")
        response = await self._client.get(
            "https://dev.to/api/articles",
            params={"top": 7, "per_page": min(limit, 50)},
        )
        response.raise_for_status()
        articles = JSON_OBJECTS.validate_python(response.json())
        items = [
            CollectedItem(
                external_id=str(self._integer(article, "id")),
                url=AnyHttpUrl(self._string(article, "url")),
                payload={**article, "rank": rank},
            )
            for rank, article in enumerate(articles, start=1)
        ]
        return FetchBatch(
            items=items,
            next_cursor=AdapterCursor(value={"snapshot": "top-7-days"}),
            has_more=False,
        )

    def normalize(self, item: CollectedItem) -> NormalizedItem:
        payload = item.payload
        user = payload.get("user")
        user_data = user if isinstance(user, dict) else {}
        tags_value = payload.get("tag_list", [])
        tags = [tag for tag in cast(list[JsonValue], tags_value) if isinstance(tag, str)]
        reactions = self._integer(payload, "public_reactions_count", default=0)
        comments = self._integer(payload, "comments_count", default=0)
        rank = self._integer(payload, "rank", default=0)
        description = self._optional_string(payload, "description") or ""
        content = (
            f"{description}\nDEV 近 7 日热门第 {rank} 位，"
            f"{reactions} 次公开反应、{comments} 条评论。"
        ).strip()
        username = self._optional_string(user_data, "username")
        author_name = self._optional_string(user_data, "name") or username
        canonical_url = (
            self._optional_string(payload, "canonical_url") or self._string(payload, "url")
        )
        return NormalizedItem(
            external_id=str(self._integer(payload, "id")),
            kind=ArticleKind.BLOG_POST,
            canonical_url=AnyHttpUrl(canonical_url),
            title=self._string(payload, "title"),
            content=content,
            published_at=datetime.fromisoformat(
                self._string(payload, "published_timestamp").replace("Z", "+00:00")
            ),
            authors=(
                [
                    AuthorData(
                        name=author_name,
                        url=AnyHttpUrl(f"https://dev.to/{username}") if username else None,
                    )
                ]
                if author_name
                else []
            ),
            tags=tags,
            metadata={
                "provider": "dev-community",
                "score": reactions,
                "reactions": reactions,
                "comments": comments,
                "rank": rank,
                "reading_time_minutes": payload.get("reading_time_minutes"),
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _string(payload: dict[str, JsonValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"DEV article is missing {key}")
        return value.strip()

    @staticmethod
    def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _integer(payload: dict[str, JsonValue], key: str, *, default: int | None = None) -> int:
        value = payload.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"DEV article has invalid {key}")
        return value
