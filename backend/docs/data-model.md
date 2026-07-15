# Unified data model and source adapter

## Storage flow

Every provider response is persisted before normalization:

```text
Source -> RawItem -> Article
              \-> source JSONB payload

Article <-> Author
Article <-> Tag
Source  -> FetchRun
```

- `Source` stores provider configuration and its incremental cursor.
- `RawItem` preserves the provider payload and common searchable fields.
- `Article` is the normalized record used by later deduplication, AI analysis, and APIs.
- `Author` and `Tag` are reusable many-to-many dimensions.
- `FetchRun` records collection progress and outcome counters.

`RawItem(source_id, external_id)` is unique. This is the first idempotency boundary: the same provider record can be fetched repeatedly without producing another raw record.

## SourceAdapter contract

Adapters are independent from SQLAlchemy sessions and implement two operations:

```python
class SourceAdapter(ABC):
    async def fetch(
        self,
        cursor: AdapterCursor | None = None,
        *,
        limit: int = 100,
    ) -> FetchBatch: ...

    def normalize(self, item: CollectedItem) -> NormalizedItem: ...
```

`FetchBatch.next_cursor` is persisted only after the batch is processed successfully. `CollectedItem.external_id` must be stable within the source. Provider-specific values remain in JSON-compatible payload or metadata fields; URL, title, content, publication time, author, and license are structured.

See `app/sources/example.py` for the reference implementation.

## Migration commands

From the repository root with Docker Compose running:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```
