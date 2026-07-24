import asyncio
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.collection.locking import source_lock_key
from app.collection.registry import SourceRegistry
from app.collection.retry import retry_async
from app.collection.runner import CollectionResult
from app.collection.scheduler import (
    SchedulerConfig,
    register_jobs,
    run_scheduled_source,
)


def test_registry_contains_all_mvp_sources() -> None:
    assert SourceRegistry().slugs == (
        "hacker-news",
        "dev-community",
        "github-releases",
        "arxiv",
        "hugging-face",
    )


def test_source_lock_key_is_stable_signed_bigint() -> None:
    first = source_lock_key("arxiv")

    assert first == source_lock_key("arxiv")
    assert first != source_lock_key("hugging-face")
    assert -(2**63) <= first < 2**63


def test_retry_uses_exponential_backoff() -> None:
    attempts: list[int] = []
    delays: list[float] = []

    async def operation(attempt: int) -> str:
        attempts.append(attempt)
        if attempt < 3:
            raise RuntimeError("temporary")
        return "ok"

    async def sleep(delay: float) -> None:
        delays.append(delay)

    result, attempt_count = asyncio.run(
        retry_async(operation, max_attempts=3, backoff_seconds=1.5, sleep=sleep)
    )

    assert result == "ok"
    assert attempt_count == 3
    assert attempts == [1, 2, 3]
    assert delays == [1.5, 3.0]


def test_schedule_registration_is_idempotent_and_serial_per_source() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config" / "schedules.json"
    config = SchedulerConfig.from_file(config_path)
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def job(_source_slug: str) -> None:
        return None

    register_jobs(scheduler, config, job_function=job)
    register_jobs(scheduler, config, job_function=job)
    jobs = sorted(scheduler.get_jobs(), key=lambda item: item.id)

    assert [job.id for job in jobs] == [
        "collect:arxiv",
        "collect:github-releases",
        "collect:hugging-face",
    ]
    assert all(job.max_instances == 1 and job.coalesce is True for job in jobs)
    assert isinstance(scheduler.get_job("collect:arxiv").trigger, IntervalTrigger)
    assert isinstance(scheduler.get_job("collect:github-releases").trigger, CronTrigger)


def test_one_scheduled_source_failure_does_not_block_another() -> None:
    class FakeRunner:
        async def run(self, source_slug: str, **_kwargs: object) -> CollectionResult:
            if source_slug == "broken":
                raise RuntimeError("provider unavailable")
            return CollectionResult(
                source=source_slug,
                status="success",
                run_id="run-1",
                attempts=1,
                fetched=1,
                inserted=1,
                updated=0,
                skipped=0,
                cursor={"offset": 1},
            )

    async def run_both() -> list[CollectionResult | None]:
        return list(
            await asyncio.gather(
                run_scheduled_source("broken", runner_factory=FakeRunner),
                run_scheduled_source("healthy", runner_factory=FakeRunner),
            )
        )

    failed, succeeded = asyncio.run(run_both())

    assert failed is None
    assert succeeded is not None
    assert succeeded.source == "healthy"
