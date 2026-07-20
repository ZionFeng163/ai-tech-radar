import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.collection.registry import SourceRegistry
from app.collection.runner import CollectionRunner
from app.collection.scheduler import DEFAULT_SCHEDULE_PATH, serve_scheduler
from app.processing import NormalizationPipeline, ProcessingConfig
from app.processing.config import DEFAULT_PROCESSING_CONFIG_PATH
from app.processing.evaluation import DEFAULT_EVALUATION_PATH, evaluate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="collect and persist one configured source")
    collect.add_argument("--source", required=True, choices=SourceRegistry().slugs)
    collect.add_argument("--limit", type=int, help="optional maximum number of items")
    collect.add_argument("--max-attempts", type=int, default=3)
    collect.add_argument("--backoff-seconds", type=float, default=1.0)

    scheduler = subparsers.add_parser("scheduler", help="run the collection scheduler")
    scheduler.add_argument("--config", type=Path, default=DEFAULT_SCHEDULE_PATH)

    normalize = subparsers.add_parser(
        "normalize", help="normalize raw items, deduplicate articles, and cluster events"
    )
    normalize.add_argument("--limit", type=int, help="optional maximum number of raw items")
    normalize.add_argument("--config", type=Path, default=DEFAULT_PROCESSING_CONFIG_PATH)
    normalize.add_argument("--evaluate", action="store_true", help="run offline evaluation only")
    normalize.add_argument("--evaluation-data", type=Path, default=DEFAULT_EVALUATION_PATH)
    return parser


async def _collect(args: argparse.Namespace) -> None:
    result = await CollectionRunner().run(
        args.source,
        limit=args.limit,
        max_attempts=args.max_attempts,
        backoff_seconds=args.backoff_seconds,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()
    if args.command == "collect":
        asyncio.run(_collect(args))
    elif args.command == "scheduler":
        asyncio.run(serve_scheduler(args.config))
    else:
        config = ProcessingConfig.from_file(args.config)
        result = (
            evaluate(config, args.evaluation_data).as_dict()
            if args.evaluate
            else NormalizationPipeline(config).run(limit=args.limit).as_dict()
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
