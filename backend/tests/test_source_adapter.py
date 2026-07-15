import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain import ArticleKind
from app.sources.base import AdapterCursor, FetchBatch, NormalizedItem
from app.sources.example import ExampleSourceAdapter


def make_record(external_id: str, kind: ArticleKind = ArticleKind.PAPER) -> NormalizedItem:
    return NormalizedItem(
        external_id=external_id,
        kind=kind,
        canonical_url=f"https://example.com/items/{external_id}",
        title=f"Item {external_id}",
        content="Technical content",
        published_at=datetime(2026, 7, 15, tzinfo=UTC),
        authors=[{"name": "Ada Lovelace", "external_ids": {"orcid": "0000-0000"}}],
        tags=["machine-learning"],
        license="Apache-2.0",
        metadata={"provider_score": 42},
    )


def test_example_adapter_fetches_pages_and_preserves_cursor() -> None:
    adapter = ExampleSourceAdapter([make_record("one"), make_record("two")])

    first = asyncio.run(adapter.fetch(limit=1))
    second = asyncio.run(adapter.fetch(first.next_cursor, limit=1))

    assert first.has_more is True
    assert first.next_cursor == AdapterCursor(value={"offset": 1})
    assert second.has_more is False
    assert second.next_cursor == AdapterCursor(value={"offset": 2})
    assert adapter.normalize(second.items[0]) == make_record("two")


def test_adapter_builds_source_scoped_deduplication_key() -> None:
    adapter = ExampleSourceAdapter([make_record("stable-id")])
    batch = asyncio.run(adapter.fetch())

    assert adapter.deduplication_key(batch.items[0]) == "example:stable-id"


def test_normalized_item_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        NormalizedItem(
            external_id="naive-time",
            kind=ArticleKind.BLOG_POST,
            canonical_url="https://example.com/naive-time",
            title="Naive timestamp",
            published_at=datetime(2026, 7, 15),
        )


def test_fetch_batch_rejects_empty_page_when_more_is_claimed() -> None:
    with pytest.raises(ValidationError, match="must contain at least one item"):
        FetchBatch(items=[], next_cursor=AdapterCursor(value={"offset": 0}), has_more=True)


@pytest.mark.parametrize(
    "kind",
    [
        ArticleKind.PAPER,
        ArticleKind.CODE_REPOSITORY,
        ArticleKind.RELEASE,
        ArticleKind.BLOG_POST,
    ],
)
def test_contract_supports_mvp_content_kinds(kind: ArticleKind) -> None:
    assert make_record("kind-check", kind).kind is kind
