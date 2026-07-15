from collections.abc import Sequence

from pydantic import AnyHttpUrl

from app.domain import SourceKind
from app.sources.base import (
    AdapterCursor,
    CollectedItem,
    FetchBatch,
    NormalizedItem,
    SourceAdapter,
    SourceDescriptor,
)


class ExampleSourceAdapter(SourceAdapter):
    """In-memory reference implementation used by tests and adapter authors."""

    descriptor = SourceDescriptor(
        slug="example",
        name="Example source",
        kind=SourceKind.OTHER,
        base_url=AnyHttpUrl("https://example.com"),
    )

    def __init__(self, records: Sequence[NormalizedItem]) -> None:
        self._records = list(records)

    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        offset_value = 0 if cursor is None else cursor.value.get("offset", 0)
        if not isinstance(offset_value, int) or isinstance(offset_value, bool) or offset_value < 0:
            raise ValueError("cursor offset must be a non-negative integer")

        page = self._records[offset_value : offset_value + limit]
        next_offset = offset_value + len(page)
        items = [
            CollectedItem(
                external_id=record.external_id,
                url=record.canonical_url,
                payload=record.model_dump(mode="json"),
            )
            for record in page
        ]
        return FetchBatch(
            items=items,
            next_cursor=AdapterCursor(value={"offset": next_offset}),
            has_more=next_offset < len(self._records),
        )

    def normalize(self, item: CollectedItem) -> NormalizedItem:
        return NormalizedItem.model_validate(item.payload)
