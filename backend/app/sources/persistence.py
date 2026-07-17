import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import RawItem, Source
from app.sources.base import FetchBatch, SourceAdapter, SourceDescriptor


@dataclass(frozen=True, slots=True)
class PersistResult:
    inserted: int
    updated: int


def ensure_source(
    session: Session,
    descriptor: SourceDescriptor,
    config: dict[str, object],
) -> Source:
    source = session.scalar(select(Source).where(Source.slug == descriptor.slug))
    if source is None:
        source = Source(
            slug=descriptor.slug,
            name=descriptor.name,
            kind=descriptor.kind,
            base_url=str(descriptor.base_url) if descriptor.base_url else None,
            config=config,
            cursor_state={},
        )
        session.add(source)
        session.flush()
    else:
        source.config = config
    return source


def persist_batch(
    session: Session,
    source: Source,
    adapter: SourceAdapter,
    batch: FetchBatch,
) -> PersistResult:
    external_ids = [item.external_id for item in batch.items]
    existing = (
        set(
            session.scalars(
                select(RawItem.external_id).where(
                    RawItem.source_id == source.id,
                    RawItem.external_id.in_(external_ids),
                )
            )
        )
        if external_ids
        else set()
    )
    now = datetime.now(UTC)

    for item in batch.items:
        normalized = adapter.normalize(item)
        payload_json = json.dumps(
            item.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        statement = insert(RawItem).values(
            source_id=source.id,
            external_id=item.external_id,
            url=str(item.url),
            title=normalized.title,
            body=normalized.content,
            authors=[author.model_dump(mode="json") for author in normalized.authors],
            license=normalized.license,
            published_at=normalized.published_at,
            fetched_at=item.fetched_at,
            content_hash=hashlib.sha256(payload_json.encode()).hexdigest(),
            source_metadata=normalized.metadata,
            raw_payload=item.payload,
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            constraint="uq_raw_items_source_external_id",
            set_={
                "url": excluded.url,
                "title": excluded.title,
                "body": excluded.body,
                "authors": excluded.authors,
                "license": excluded.license,
                "published_at": excluded.published_at,
                "fetched_at": excluded.fetched_at,
                "content_hash": excluded.content_hash,
                "metadata": excluded.metadata,
                "raw_payload": excluded.raw_payload,
                "updated_at": now,
            },
        )
        session.execute(statement)

    source.cursor_state = dict(batch.next_cursor.value)
    session.commit()
    inserted = len(set(external_ids) - existing)
    return PersistResult(inserted=inserted, updated=len(external_ids) - inserted)
