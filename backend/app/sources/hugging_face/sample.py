import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.domain import FetchRunStatus
from app.models import FetchRun, Source
from app.sources.base import AdapterCursor
from app.sources.hugging_face.adapter import HuggingFaceAdapter
from app.sources.hugging_face.config import HuggingFaceConfig
from app.sources.hugging_face.persistence import ensure_hugging_face_source, persist_batch

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "sources" / "hugging-face.json"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect a bounded Hugging Face Hub sample")
    parser.add_argument("--limit", type=int, default=3, help="maximum Hub items to fetch")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--resource-type", action="append", dest="resource_types")
    parser.add_argument("--model-task", action="append", dest="model_tasks")
    parser.add_argument("--dataset-filter", action="append", dest="dataset_filters")
    parser.add_argument("--author", action="append", dest="authors")
    parser.add_argument("--organization", action="append", dest="organizations")
    parser.add_argument("--window-hours", type=int)
    parser.add_argument("--persist", action="store_true", help="upsert RawItem rows and cursor")
    return parser.parse_args()


def _config(args: argparse.Namespace) -> HuggingFaceConfig:
    config = (
        HuggingFaceConfig.from_file(args.config) if args.config.exists() else HuggingFaceConfig()
    )
    values = config.model_dump()
    for argument in (
        "resource_types",
        "model_tasks",
        "dataset_filters",
        "authors",
        "organizations",
    ):
        if value := getattr(args, argument):
            values[argument] = value
    if args.window_hours is not None:
        values["initial_window_hours"] = args.window_hours
    if token := os.getenv("HF_TOKEN"):
        values["token"] = token
    return HuggingFaceConfig.model_validate(values)


def _start_run(session: Session, source: Source, config: HuggingFaceConfig) -> FetchRun:
    run = FetchRun(
        source_id=source.id,
        cursor_before=source.cursor_state,
        run_metadata={"authentication": "token" if config.token else "anonymous"},
    )
    session.add(run)
    session.commit()
    return run


async def collect_sample(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit < 1:
        raise ValueError("limit must be at least 1")
    config = _config(args)
    session: Session | None = SessionLocal() if args.persist else None
    source: Source | None = None
    run: FetchRun | None = None
    cursor: AdapterCursor | None = None

    if session is not None:
        source = ensure_hugging_face_source(session, config)
        session.commit()
        cursor = (
            AdapterCursor.model_validate({"value": source.cursor_state})
            if source.cursor_state
            else None
        )
        run = _start_run(session, source, config)

    summary: dict[str, Any] = {
        "authentication": "token" if config.token else "anonymous",
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "items": [],
    }
    try:
        async with HuggingFaceAdapter(config) as adapter:
            while summary["fetched"] < args.limit:
                remaining = args.limit - int(summary["fetched"])
                batch = await adapter.fetch(cursor, limit=remaining)
                if not batch.items:
                    if session is not None and source is not None:
                        persist_batch(session, source, adapter, batch)
                    cursor = batch.next_cursor
                    break

                for item in batch.items:
                    normalized = adapter.normalize(item)
                    summary["items"].append(
                        {
                            "external_id": normalized.external_id,
                            "kind": normalized.kind.value,
                            "title": normalized.title,
                            "updated_at": (
                                normalized.updated_at.isoformat() if normalized.updated_at else None
                            ),
                            "downloads": normalized.metadata.get("downloads"),
                            "likes": normalized.metadata.get("likes"),
                            "url": str(normalized.canonical_url),
                        }
                    )
                summary["fetched"] += len(batch.items)
                if session is not None and source is not None:
                    result = persist_batch(session, source, adapter, batch)
                    summary["inserted"] += result.inserted
                    summary["updated"] += result.updated
                cursor = batch.next_cursor
                if not batch.has_more:
                    break

        errors = cursor.value.get("errors", []) if cursor else []
        summary["errors"] = errors
        if session is not None and run is not None:
            run.status = FetchRunStatus.PARTIAL if errors else FetchRunStatus.SUCCESS
            run.finished_at = datetime.now(UTC)
            run.cursor_after = cast(dict[str, object], cursor.value) if cursor else {}
            run.items_fetched = int(summary["fetched"])
            run.items_stored = int(summary["inserted"]) + int(summary["updated"])
            run.items_skipped = len(cast(list[object], errors))
            session.commit()
        summary["cursor"] = cursor.value if cursor else {}
        return summary
    except Exception as error:
        if session is not None and run is not None:
            session.rollback()
            run.status = FetchRunStatus.FAILED
            run.finished_at = datetime.now(UTC)
            run.error_summary = str(error)[:2_000]
            session.commit()
        raise
    finally:
        if session is not None:
            session.close()


def main() -> None:
    result = asyncio.run(collect_sample(_arguments()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
