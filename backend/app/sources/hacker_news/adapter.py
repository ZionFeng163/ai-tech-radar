import asyncio
import html
import re
from datetime import UTC, datetime

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

STORY_IDS = TypeAdapter(list[int])
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
TAG_RE = re.compile(r"<[^>]+>")


class HackerNewsAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        slug="hacker-news",
        name="Hacker News",
        kind=SourceKind.OTHER,
        base_url=AnyHttpUrl("https://news.ycombinator.com"),
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
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        )
        response.raise_for_status()
        story_ids = STORY_IDS.validate_python(response.json())[: min(limit, 50)]
        stories = await asyncio.gather(*(self._fetch_story(story_id) for story_id in story_ids))
        items = [
            CollectedItem(
                external_id=str(story["id"]),
                url=AnyHttpUrl(f"https://news.ycombinator.com/item?id={story['id']}"),
                payload={**story, "rank": rank},
            )
            for rank, story in enumerate(stories, start=1)
            if story
        ]
        return FetchBatch(
            items=items,
            next_cursor=AdapterCursor(value={"snapshot": "topstories"}),
            has_more=False,
        )

    async def _fetch_story(self, story_id: int) -> dict[str, JsonValue]:
        response = await self._client.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        response.raise_for_status()
        story = JSON_OBJECT.validate_python(response.json())
        if (
            story.get("type") != "story"
            or story.get("dead") is True
            or story.get("deleted") is True
        ):
            return {}
        return story

    def normalize(self, item: CollectedItem) -> NormalizedItem:
        payload = item.payload
        story_id = self._integer(payload, "id")
        score = self._integer(payload, "score", default=0)
        comments = self._integer(payload, "descendants", default=0)
        rank = self._integer(payload, "rank", default=0)
        title = self._string(payload, "title")
        author = self._optional_string(payload, "by")
        target_url = self._optional_string(payload, "url") or str(item.url)
        story_text = self._clean_html(self._optional_string(payload, "text") or "")
        context = (
            f"Hacker News 热门榜第 {rank} 位，{score} 票、{comments} 条评论。"
            f"{story_text}"
        ).strip()
        return NormalizedItem(
            external_id=str(story_id),
            kind=ArticleKind.NEWS,
            canonical_url=AnyHttpUrl(target_url),
            title=title,
            content=context,
            published_at=datetime.fromtimestamp(self._integer(payload, "time"), tz=UTC),
            authors=(
                [
                    AuthorData(
                        name=author,
                        url=AnyHttpUrl(f"https://news.ycombinator.com/user?id={author}"),
                    )
                ]
                if author
                else []
            ),
            tags=["Hacker News", "社区热点"],
            metadata={
                "provider": "hacker-news",
                "score": score,
                "comments": comments,
                "rank": rank,
                "discussion_url": str(item.url),
                "target_url": target_url,
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _string(payload: dict[str, JsonValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Hacker News story is missing {key}")
        return value.strip()

    @staticmethod
    def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _integer(payload: dict[str, JsonValue], key: str, *, default: int | None = None) -> int:
        value = payload.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"Hacker News story has invalid {key}")
        return value

    @staticmethod
    def _clean_html(value: str) -> str:
        return html.unescape(TAG_RE.sub(" ", value)).replace("\n", " ").strip()
