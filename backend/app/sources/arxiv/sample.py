import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.domain import FetchRunStatus
from app.models import FetchRun, Source
from app.sources.arxiv.adapter import ArxivAdapter
from app.sources.arxiv.config import ArxivConfig
from app.sources.arxiv.persistence import ensure_arxiv_source, persist_batch
from app.sources.base import AdapterCursor


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect a bounded sample from the arXiv API")
    parser.add_argument("--limit", type=int, default=3, help="maximum papers to fetch")
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--keyword", action="append", dest="keywords")
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--persist", action="store_true", help="upsert RawItem rows and cursor")
    return parser.parse_args()


def _config(args: argparse.Namespace) -> ArxivConfig:
    values: dict[str, Any] = {"window_hours": args.window_hours}
    if args.categories:
        values["categories"] = args.categories
    if args.keywords:
        values["keywords"] = args.keywords
    return ArxivConfig.model_validate(values)


def _start_run(session: Session, source: Source) -> FetchRun:
    run = FetchRun(source_id=source.id, cursor_before=source.cursor_state)
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
        source = ensure_arxiv_source(session, config)
        session.commit()
        cursor = (
            AdapterCursor.model_validate({"value": source.cursor_state})
            if source.cursor_state
            else None
        )
        run = _start_run(session, source)

    summary: dict[str, Any] = {
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "papers": [],
    }
    try:
        async with ArxivAdapter(config) as adapter:
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
                    summary["papers"].append(
                        {
                            "external_id": normalized.external_id,
                            "title": normalized.title,
                            "published_at": normalized.published_at.isoformat(),
                            "pdf_url": normalized.metadata.get("pdf_url"),
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

        if session is not None and run is not None:
            run.status = FetchRunStatus.SUCCESS
            run.finished_at = datetime.now(UTC)
            run.cursor_after = cast(dict[str, object], cursor.value) if cursor else {}
            run.items_fetched = int(summary["fetched"])
            run.items_stored = int(summary["inserted"]) + int(summary["updated"])
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
