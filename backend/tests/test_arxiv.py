import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.domain import ArticleKind
from app.sources.arxiv import ArxivAdapter, ArxivConfig
from app.sources.arxiv.parser import parse_feed
from app.sources.base import AdapterCursor, CollectedItem

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_feed.xml"
NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


def fixture_xml() -> bytes:
    return FIXTURE.read_bytes()


def test_parse_and_normalize_arxiv_atom_fields() -> None:
    feed = parse_feed(fixture_xml())
    adapter = ArxivAdapter(ArxivConfig(request_interval_seconds=0))
    payload = feed.entries[0]

    assert feed.total_results == 2
    assert payload["external_id"] == "2607.01234"
    assert payload["versioned_id"] == "2607.01234v2"
    assert payload["version"] == 2
    assert payload["authors"] == [{"name": "Ada Lovelace"}, {"name": "Alan Turing"}]
    assert payload["categories"] == ["cs.AI", "cs.LG"]
    assert payload["pdf_url"] == "https://arxiv.org/pdf/2607.01234v2"

    item = CollectedItem(
        external_id="2607.01234",
        url="https://arxiv.org/abs/2607.01234v2",
        payload=payload,
    )
    normalized = adapter.normalize(item)
    assert normalized.kind is ArticleKind.PAPER
    assert normalized.external_id == "2607.01234"
    assert normalized.title == "Radar Networks: A Test Paper"
    assert normalized.published_at == datetime(2026, 7, 14, 3, 0, tzinfo=UTC)
    assert normalized.updated_at == datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
    assert [author.name for author in normalized.authors] == [
        "Ada Lovelace",
        "Alan Turing",
    ]
    assert normalized.metadata["primary_category"] == "cs.AI"
    assert normalized.metadata["updated_at"] == "2026-07-15T08:30:00Z"
    asyncio.run(adapter.aclose())


def test_query_supports_categories_keywords_and_time_window() -> None:
    config = ArxivConfig(
        categories=["cs.AI", "cs.LG"],
        keywords=["large language model", "agents"],
    )
    adapter = ArxivAdapter(
        config,
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )
    query = adapter.build_search_query(
        datetime(2026, 7, 14, 10, 0, tzinfo=UTC),
        NOW,
    )

    assert "(cat:cs.AI OR cat:cs.LG)" in query
    assert '(all:"large language model" OR all:"agents")' in query
    assert "submittedDate:[202607141000 TO 202607151000]" in query


def test_fetch_paginates_with_fixed_window_then_emits_watermark() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        start = int(request.url.params["start"])
        xml = fixture_xml()
        if start == 0:
            xml = xml.replace(b"<opensearch:itemsPerPage>2", b"<opensearch:itemsPerPage>1")
            xml = xml.replace(
                xml[xml.index(b"  <entry>", xml.index(b"  <entry>") + 1) : xml.index(b"</feed>")],
                b"",
            )
        else:
            first_start = xml.index(b"  <entry>")
            second_start = xml.index(b"  <entry>", first_start + 1)
            xml = xml[:first_start] + xml[second_start:]
            xml = xml.replace(b"<opensearch:startIndex>0", b"<opensearch:startIndex>1")
            xml = xml.replace(b"<opensearch:itemsPerPage>2", b"<opensearch:itemsPerPage>1")
        return httpx.Response(200, content=xml, request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = ArxivAdapter(
                ArxivConfig(page_size=1, request_interval_seconds=0),
                client=client,
                clock=lambda: NOW,
            )
            first = await adapter.fetch(limit=10)
            second = await adapter.fetch(first.next_cursor, limit=10)

        assert first.has_more is True
        assert first.next_cursor.value == {
            "window_start": "2026-07-14T10:00:00+00:00",
            "window_end": "2026-07-15T10:00:00+00:00",
            "offset": 1,
        }
        assert second.has_more is False
        assert second.next_cursor == AdapterCursor(value={"watermark": "2026-07-15T10:00:00+00:00"})
        assert [request.url.params["start"] for request in requests] == ["0", "1"]
        assert requests[0].url.params["search_query"] == requests[1].url.params["search_query"]

    asyncio.run(scenario())


def test_fetch_retries_transient_response() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, content=fixture_xml(), request=request)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = ArxivAdapter(
                ArxivConfig(
                    request_interval_seconds=0,
                    retry_backoff_seconds=0.25,
                    max_retries=1,
                ),
                client=client,
                clock=lambda: NOW,
                sleep=sleep,
            )
            batch = await adapter.fetch(limit=2)
            assert len(batch.items) == 2

    asyncio.run(scenario())
    assert attempts == 2
    assert delays == [0.25]


def test_invalid_cursor_offset_is_rejected() -> None:
    adapter = ArxivAdapter(
        ArxivConfig(request_interval_seconds=0),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
        clock=lambda: NOW,
    )
    cursor = AdapterCursor(
        value={
            "window_start": "2026-07-14T10:00:00+00:00",
            "window_end": "2026-07-15T10:00:00+00:00",
            "offset": -1,
        }
    )

    with pytest.raises(ValueError, match="non-negative"):
        asyncio.run(adapter.fetch(cursor))
