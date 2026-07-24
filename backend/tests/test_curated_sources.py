import asyncio

import httpx

from app.sources.dev_community import DevCommunityAdapter
from app.sources.hacker_news import HackerNewsAdapter


def test_hacker_news_adapter_preserves_rank_and_engagement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/topstories.json"):
            return httpx.Response(200, json=[101])
        return httpx.Response(
            200,
            json={
                "id": 101,
                "type": "story",
                "by": "alice",
                "time": 1_750_000_000,
                "title": "A faster compiler",
                "url": "https://example.com/compiler",
                "score": 321,
                "descendants": 87,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HackerNewsAdapter(client=client)
    batch = asyncio.run(adapter.fetch(limit=1))
    normalized = adapter.normalize(batch.items[0])
    asyncio.run(client.aclose())

    assert normalized.title == "A faster compiler"
    assert normalized.metadata["score"] == 321
    assert normalized.metadata["comments"] == 87
    assert normalized.metadata["rank"] == 1
    assert "321 票" in (normalized.content or "")


def test_dev_community_adapter_uses_popularity_metadata() -> None:
    payload = [
        {
            "id": 202,
            "title": "Practical agents",
            "description": "A field guide to reliable tool use.",
            "url": "https://dev.to/alice/practical-agents",
            "canonical_url": "https://dev.to/alice/practical-agents",
            "published_timestamp": "2026-07-22T08:00:00Z",
            "tag_list": ["ai", "agents"],
            "comments_count": 34,
            "public_reactions_count": 280,
            "reading_time_minutes": 8,
            "user": {"name": "Alice", "username": "alice"},
        }
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = DevCommunityAdapter(client=client)
    batch = asyncio.run(adapter.fetch(limit=1))
    normalized = adapter.normalize(batch.items[0])
    asyncio.run(client.aclose())

    assert normalized.tags == ["ai", "agents"]
    assert normalized.metadata["reactions"] == 280
    assert normalized.metadata["comments"] == 34
    assert "近 7 日热门第 1 位" in (normalized.content or "")
