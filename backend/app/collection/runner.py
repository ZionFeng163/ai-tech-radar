import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.collection.locking import source_run_lock
from app.collection.registry import RegisteredSource, SourceRegistry
from app.collection.retry import Sleep, retry_async
from app.db import SessionLocal
from app.domain import FetchRunStatus
from app.models import FetchRun, Source
from app.sources.base import AdapterCursor
from app.sources.persistence import ensure_source, persist_batch


@dataclass(slots=True)
class CollectionProgress:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    cursor: AdapterCursor | None = None
    errors: list[object] = field(default_factory=list)

    @property
    def stored(self) -> int:
        return self.inserted + self.updated


@dataclass(frozen=True, slots=True)
class CollectionResult:
    source: str
    status: str
    run_id: str | None
    attempts: int
    fetched: int
    inserted: int
    updated: int
    skipped: int
    cursor: dict[str, object]
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "status": self.status,
            "run_id": self.run_id,
            "attempts": self.attempts,
            "fetched": self.fetched,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "cursor": self.cursor,
            "message": self.message,
        }


class CollectionRunner:
    def __init__(self, registry: SourceRegistry | None = None) -> None:
        self.registry = registry or SourceRegistry()

    async def run(
        self,
        source_slug: str,
        *,
        limit: int | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        trigger: str = "manual",
        sleep: Sleep | None = None,
    ) -> CollectionResult:
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        runtime = self.registry.get(source_slug)

        with source_run_lock(source_slug) as acquired:
            if not acquired:
                return CollectionResult(
                    source=source_slug,
                    status="skipped",
                    run_id=None,
                    attempts=0,
                    fetched=0,
                    inserted=0,
                    updated=0,
                    skipped=0,
                    cursor={},
                    message="another collection run already holds the source lock",
                )

            source_id, run_id, initial_cursor = self._prepare_run(runtime, trigger)
            progress = CollectionProgress(cursor=initial_cursor)
            retry_errors: list[dict[str, object]] = []

            def record_retry(attempt: int, error: Exception, delay: float) -> None:
                retry_errors.append(
                    {"attempt": attempt, "error": str(error)[:500], "delay_seconds": delay}
                )

            async def collect_attempt(_attempt: int) -> None:
                await self._collect_attempt(runtime, source_id, progress, limit)

            attempts = 0
            try:
                if sleep is None:
                    _, attempts = await retry_async(
                        collect_attempt,
                        max_attempts=max_attempts,
                        backoff_seconds=backoff_seconds,
                        on_retry=record_retry,
                    )
                else:
                    _, attempts = await retry_async(
                        collect_attempt,
                        max_attempts=max_attempts,
                        backoff_seconds=backoff_seconds,
                        sleep=sleep,
                        on_retry=record_retry,
                    )
            except Exception as error:
                attempts = len(retry_errors) + 1
                self._finish_run(
                    run_id,
                    FetchRunStatus.FAILED,
                    progress,
                    attempts=attempts,
                    max_attempts=max_attempts,
                    trigger=trigger,
                    retry_errors=retry_errors,
                    error_summary=str(error),
                )
                raise

            status = FetchRunStatus.PARTIAL if progress.errors else FetchRunStatus.SUCCESS
            self._finish_run(
                run_id,
                status,
                progress,
                attempts=attempts,
                max_attempts=max_attempts,
                trigger=trigger,
                retry_errors=retry_errors,
                error_summary=(
                    json.dumps(progress.errors, ensure_ascii=False, default=str)
                    if progress.errors
                    else None
                ),
            )
            return CollectionResult(
                source=source_slug,
                status=status.value,
                run_id=str(run_id),
                attempts=attempts,
                fetched=progress.fetched,
                inserted=progress.inserted,
                updated=progress.updated,
                skipped=len(progress.errors),
                cursor=cast(dict[str, object], dict(progress.cursor.value))
                if progress.cursor
                else {},
            )

    @staticmethod
    def _prepare_run(
        runtime: RegisteredSource, trigger: str
    ) -> tuple[UUID, UUID, AdapterCursor | None]:
        with SessionLocal() as session:
            source = ensure_source(session, runtime.descriptor, runtime.persisted_config)
            session.commit()
            cursor = (
                AdapterCursor.model_validate({"value": source.cursor_state})
                if source.cursor_state
                else None
            )
            run = FetchRun(
                source_id=source.id,
                cursor_before=dict(source.cursor_state),
                run_metadata={"trigger": trigger, "attempts": 0},
            )
            session.add(run)
            session.commit()
            return source.id, run.id, cursor

    @staticmethod
    async def _collect_attempt(
        runtime: RegisteredSource,
        source_id: UUID,
        progress: CollectionProgress,
        limit: int | None,
    ) -> None:
        with SessionLocal() as session:
            source = session.get(Source, source_id)
            if source is None:
                raise RuntimeError(f"source {runtime.descriptor.slug!r} no longer exists")
            cursor = (
                AdapterCursor.model_validate({"value": source.cursor_state})
                if source.cursor_state
                else None
            )
            adapter = runtime.adapter_factory()
            try:
                while limit is None or progress.fetched < limit:
                    remaining = runtime.page_size
                    if limit is not None:
                        remaining = min(remaining, limit - progress.fetched)
                    batch = await adapter.fetch(cursor, limit=remaining)
                    persisted = persist_batch(session, source, adapter, batch)
                    progress.fetched += len(batch.items)
                    progress.inserted += persisted.inserted
                    progress.updated += persisted.updated
                    cursor = batch.next_cursor
                    progress.cursor = cursor
                    raw_errors = cursor.value.get("errors", [])
                    progress.errors = list(raw_errors) if isinstance(raw_errors, list) else []
                    if not batch.items or not batch.has_more:
                        break
            finally:
                await adapter.aclose()

    @staticmethod
    def _finish_run(
        run_id: UUID,
        status: FetchRunStatus,
        progress: CollectionProgress,
        *,
        attempts: int,
        max_attempts: int,
        trigger: str,
        retry_errors: list[dict[str, object]],
        error_summary: str | None,
    ) -> None:
        with SessionLocal() as session:
            run = session.get(FetchRun, run_id)
            if run is None:
                raise RuntimeError(f"fetch run {run_id} no longer exists")
            run.status = status
            run.finished_at = datetime.now(UTC)
            run.cursor_after = (
                cast(dict[str, object], dict(progress.cursor.value)) if progress.cursor else {}
            )
            run.items_fetched = progress.fetched
            run.items_stored = progress.stored
            run.items_skipped = len(progress.errors)
            run.error_summary = error_summary[:2_000] if error_summary else None
            run.run_metadata = {
                "trigger": trigger,
                "attempts": attempts,
                "max_attempts": max_attempts,
                "retry_errors": retry_errors,
            }
            session.commit()
