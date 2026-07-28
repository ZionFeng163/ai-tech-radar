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
FEEDS = ("topstories", "beststories", "newstories")
TECH_TERMS = (
    " ai ",
    "agent",
    "artificial intelligence",
    "claude",
    "codex",
    "cuda",
    "deepseek",
    "gpt",
    "gpu",
    "kimi",
    "language model",
    "llm",
    "machine learning",
    "model",
    "moonshot",
    "neural",
    "open source",
    "qwen",
    "robot",
    "transformer",
)


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
        feed_results = await asyncio.gather(
            *(self._fetch_feed(feed) for feed in FEEDS)
        )
        story_feeds: dict[int, list[tuple[str, int]]] = {}
        candidates_per_feed = min(max(limit * 3, 60), 100)
        for feed, story_ids in zip(FEEDS, feed_results, strict=True):
            for rank, story_id in enumerate(story_ids[:candidates_per_feed], start=1):
                story_feeds.setdefault(story_id, []).append((feed, rank))
        semaphore = asyncio.Semaphore(20)
        story_results = await asyncio.gather(
            *(
                self._fetch_story_safely(story_id, semaphore)
                for story_id in story_feeds
            )
        )
        stories = [story for story in story_results if story]
        hottest = sorted(stories, key=self._engagement_score, reverse=True)
        general_quota = min(limit, max(5, limit // 3))
        selected = hottest[:general_quota]
        selected_ids = {self._integer(story, "id") for story in selected}
        relevant = sorted(
            (
                story
                for story in stories
                if self._integer(story, "id") not in selected_ids
                and self._is_relevant(story)
            ),
            key=self._engagement_score,
            reverse=True,
        )
        for story in relevant:
            if len(selected) >= limit:
                break
            selected.append(story)
            selected_ids.add(self._integer(story, "id"))
        for story in hottest:
            if len(selected) >= limit:
                break
            story_id = self._integer(story, "id")
            if story_id not in selected_ids:
                selected.append(story)
                selected_ids.add(story_id)
        items = [
            CollectedItem(
                external_id=str(story["id"]),
                url=AnyHttpUrl(f"https://news.ycombinator.com/item?id={story['id']}"),
                payload={
                    **story,
                    "rank": rank,
                    "feeds": [
                        {"name": feed, "rank": feed_rank}
                        for feed, feed_rank in story_feeds[
                            self._integer(story, "id")
                        ]
                    ],
                },
            )
            for rank, story in enumerate(selected, start=1)
        ]
        return FetchBatch(
            items=items,
            next_cursor=AdapterCursor(value={"snapshot": list(FEEDS)}),
            has_more=False,
        )

    async def _fetch_feed(self, feed: str) -> list[int]:
        response = await self._client.get(
            f"https://hacker-news.firebaseio.com/v0/{feed}.json"
        )
        response.raise_for_status()
        return STORY_IDS.validate_python(response.json())

    async def _fetch_story_safely(
        self, story_id: int, semaphore: asyncio.Semaphore
    ) -> dict[str, JsonValue]:
        async with semaphore:
            try:
                return await self._fetch_story(story_id)
            except (httpx.HTTPError, ValueError):
                return {}

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
                "feeds": payload.get("feeds", []),
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

    @classmethod
    def _engagement_score(cls, story: dict[str, JsonValue]) -> int:
        return cls._integer(story, "score", default=0) + (
            2 * cls._integer(story, "descendants", default=0)
        )

    @classmethod
    def _is_relevant(cls, story: dict[str, JsonValue]) -> bool:
        title = cls._optional_string(story, "title") or ""
        text = cls._optional_string(story, "text") or ""
        haystack = f" {title} {text} ".casefold()
        return any(term in haystack for term in TECH_TERMS)
