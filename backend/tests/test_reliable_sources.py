import asyncio
from datetime import UTC, datetime

import httpx

from app.domain import ArticleKind
from app.sources.hugging_face_papers import (
    HuggingFacePapersAdapter,
    HuggingFacePapersConfig,
)

NOW = datetime(2026, 7, 28, 3, 0, tzinfo=UTC)


def test_hugging_face_daily_papers_uses_curated_submission_time() -> None:
    response = [
        {
            "publishedAt": "2026-07-28T00:00:00Z",
            "paper": {
                "id": "2607.08662",
                "title": "WebSwarm",
                "summary": "Dynamic organization for multi-agent web research.",
                "publishedAt": "2026-07-10T00:00:00Z",
                "submittedOnDailyAt": "2026-07-28T01:00:00Z",
                "upvotes": 124,
                "discussionId": "discussion-1",
                "authors": [{"name": "Alice", "_id": "author-1"}],
            },
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/daily_papers"
        return httpx.Response(200, json=response, request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HuggingFacePapersAdapter(
                HuggingFacePapersConfig(initial_window_hours=72, max_retries=0),
                client=client,
                clock=lambda: NOW,
            )
            batch = await adapter.fetch(limit=5)
            normalized = adapter.normalize(batch.items[0])

        assert normalized.kind is ArticleKind.PAPER
        assert normalized.external_id == "paper:2607.08662"
        assert normalized.published_at == datetime(
            2026, 7, 28, 1, 0, tzinfo=UTC
        )
        assert normalized.metadata["upvotes"] == 124
        assert str(normalized.canonical_url) == "https://huggingface.co/papers/2607.08662"

    asyncio.run(scenario())
