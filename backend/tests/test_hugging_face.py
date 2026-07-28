import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.domain import ArticleKind
from app.sources.hugging_face import (
    HuggingFaceAdapter,
    HuggingFaceConfig,
    HuggingFaceResourceType,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)


def load_json(name: str):  # type: ignore[no-untyped-def]
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_config_supports_required_tasks_and_does_not_persist_token() -> None:
    config = HuggingFaceConfig(token="do-not-store")
    from_file = HuggingFaceConfig.from_file(
        Path(__file__).parents[1] / "config" / "sources" / "hugging-face.json"
    )

    assert {
        "text-generation",
        "image-text-to-text",
        "automatic-speech-recognition",
    }.issubset(config.model_tasks)
    assert from_file.resource_types == [HuggingFaceResourceType.MODEL]
    assert from_file.include_recent_updates is False
    assert "token" not in config.persisted_config()
    assert config.persisted_config()["authentication"] == "token"


def test_model_pagination_watermark_and_bad_item_isolation() -> None:
    model = load_json("hugging_face_models.json")[0]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-token"
        if "cursor" in request.url.params:
            old = {**model, "id": "acme/old", "lastModified": "2026-07-15T00:00:00Z"}
            return httpx.Response(200, json=[old], request=request)
        return httpx.Response(
            200,
            json=[model, {"id": "acme/bad", "lastModified": "not-a-date"}],
            headers={
                "Link": ('<https://huggingface.co/api/models?limit=2&cursor=opaque>; rel="next"')
            },
            request=request,
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HuggingFaceAdapter(
                HuggingFaceConfig(
                    token="test-token",
                    resource_types=[HuggingFaceResourceType.MODEL],
                    model_tasks=["text-generation"],
                    include_global_trending_models=False,
                    initial_window_hours=24,
                    overlap_seconds=0,
                    request_interval_seconds=0,
                ),
                client=client,
                clock=lambda: NOW,
            )
            first = await adapter.fetch(limit=2)
            normalized = adapter.normalize(first.items[0])
            final = await adapter.fetch(first.next_cursor, limit=2)

        assert first.has_more is True
        assert first.items[0].external_id == "model:acme/RadarLM-1B"
        assert normalized.kind is ArticleKind.MODEL
        assert normalized.title == "RadarLM 1B"
        assert normalized.content == "A compact model for technical radar classification."
        assert normalized.license == "apache-2.0"
        assert normalized.metadata["downloads"] == 2048
        assert normalized.authors[0].name == "acme"
        assert final.items == []
        assert final.has_more is False
        assert final.next_cursor.value["completed"] is True
        assert final.next_cursor.value["errors"][0]["item_id"] == "acme/bad"
        assert (
            final.next_cursor.value["watermarks"][
                "model|text-generation|*|lastModified"
            ]
            == "2026-07-17T03:00:00+00:00"
        )

    asyncio.run(scenario())
    assert len(requests) == 2
    assert requests[0].url.params["pipeline_tag"] == "text-generation"
    assert requests[0].url.params["sort"] == "lastModified"
    assert requests[0].url.params["direction"] == "-1"


def test_dataset_filter_author_and_normalization() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/datasets"
        assert request.url.params["filter"] == "task_categories:text-classification"
        assert request.url.params["author"] == "acme"
        assert request.url.params["full"] == "true"
        return httpx.Response(
            200,
            json=load_json("hugging_face_datasets.json"),
            request=request,
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HuggingFaceAdapter(
                HuggingFaceConfig(
                    resource_types=[HuggingFaceResourceType.DATASET],
                    dataset_filters=["task_categories:text-classification"],
                    organizations=["acme"],
                    include_global_trending_models=False,
                    initial_window_hours=48,
                    request_interval_seconds=0,
                ),
                client=client,
                clock=lambda: NOW,
            )
            batch = await adapter.fetch(limit=5)
            normalized = adapter.normalize(batch.items[0])

        assert batch.has_more is False
        assert normalized.kind is ArticleKind.DATASET
        assert normalized.external_id == "dataset:acme/radar-events"
        assert normalized.title == "Radar Events"
        assert normalized.content == "A structured dataset of AI technology events."
        assert normalized.license == "cc-by-4.0,mit"
        assert normalized.metadata["likes"] == 12

    asyncio.run(scenario())


def test_optional_readme_enrichment_provides_analysis_content() -> None:
    model = load_json("hugging_face_models.json")[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/raw/main/README.md"):
            return httpx.Response(
                200,
                text="# RadarLM\n\nUses grouped-query attention for lower-memory inference.",
                request=request,
            )
        return httpx.Response(200, json=[{**model, "description": None}], request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HuggingFaceAdapter(
                HuggingFaceConfig(
                    resource_types=[HuggingFaceResourceType.MODEL],
                    model_tasks=["text-generation"],
                    include_global_trending_models=False,
                    fetch_readme=True,
                    request_interval_seconds=0,
                ),
                client=client,
                clock=lambda: NOW,
            )
            batch = await adapter.fetch(limit=1)
            normalized = adapter.normalize(batch.items[0])

        assert "grouped-query attention" in (normalized.content or "")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("headers", "expected_delay"),
    [
        ({"Retry-After": "5"}, 5.0),
        ({"RateLimit": '"api";r=0;t=7'}, 7.0),
    ],
)
def test_rate_limit_waits_then_retries(
    headers: dict[str, str],
    expected_delay: float,
) -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers=headers, request=request)
        return httpx.Response(200, json=[], request=request)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HuggingFaceAdapter(
                HuggingFaceConfig(
                    resource_types=[HuggingFaceResourceType.MODEL],
                    model_tasks=["text-generation"],
                    include_global_trending_models=False,
                    max_retries=1,
                    request_interval_seconds=0,
                ),
                client=client,
                clock=lambda: NOW,
                sleep=sleep,
            )
            batch = await adapter.fetch()
            assert batch.items == []

    asyncio.run(scenario())
    assert calls == 2
    assert delays == [expected_delay]


def test_failed_query_does_not_block_the_next_task() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["pipeline_tag"] == "broken-task":
            return httpx.Response(500, request=request)
        return httpx.Response(
            200,
            json=load_json("hugging_face_models.json"),
            request=request,
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HuggingFaceAdapter(
                HuggingFaceConfig(
                    resource_types=[HuggingFaceResourceType.MODEL],
                    model_tasks=["broken-task", "text-generation"],
                    include_global_trending_models=False,
                    initial_window_hours=24,
                    max_retries=0,
                    request_interval_seconds=0,
                ),
                client=client,
                clock=lambda: NOW,
            )
            batch = await adapter.fetch()

        assert len(batch.items) == 1
        assert batch.has_more is False
        assert (
            batch.next_cursor.value["errors"][0]["query"]
            == "model|broken-task|*|lastModified"
        )

    asyncio.run(scenario())


def test_global_trending_uses_platform_score_and_current_signal_time() -> None:
    payload = {
        "id": "moonshotai/Kimi-K3",
        "author": "moonshotai",
        "createdAt": "2026-06-20T08:00:00Z",
        "lastModified": "2026-07-27T16:29:18Z",
        "likes": 6477,
        "trendingScore": 6075,
        "pipeline_tag": "image-text-to-text",
        "tags": ["transformers"],
        "cardData": {"license": "modified-mit"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["sort"] == "trendingScore"
        assert "pipeline_tag" not in request.url.params
        return httpx.Response(200, json=[payload], request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HuggingFaceAdapter(
                HuggingFaceConfig(
                    resource_types=[HuggingFaceResourceType.MODEL],
                    model_tasks=[],
                    include_global_trending_models=True,
                    include_recent_updates=False,
                    request_interval_seconds=0,
                ),
                client=client,
                clock=lambda: NOW,
            )
            batch = await adapter.fetch(limit=5)
            normalized = adapter.normalize(batch.items[0])

        assert normalized.external_id == "model:moonshotai/Kimi-K3"
        assert normalized.published_at == datetime(
            2026, 7, 27, 16, 29, 18, tzinfo=UTC
        )
        assert normalized.metadata["trending_score"] == 6075
        assert batch.has_more is False

    asyncio.run(scenario())
