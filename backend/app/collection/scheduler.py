import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.collection.runner import CollectionResult, CollectionRunner

LOGGER = logging.getLogger(__name__)
DEFAULT_SCHEDULE_PATH = Path(__file__).resolve().parents[2] / "config" / "schedules.json"
RunnerFactory = Callable[[], CollectionRunner]
ScheduledCallable = Callable[[str], object]


class SourceSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    trigger: Literal["interval", "cron"]
    interval_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    cron: str | None = None

    @model_validator(mode="after")
    def validate_trigger_settings(self) -> "SourceSchedule":
        if self.trigger == "interval" and self.interval_minutes is None:
            raise ValueError("interval schedules require interval_minutes")
        if self.trigger == "cron" and not self.cron:
            raise ValueError("cron schedules require a five-field cron expression")
        return self

    def build_trigger(self) -> IntervalTrigger | CronTrigger:
        if self.trigger == "interval":
            return IntervalTrigger(minutes=self.interval_minutes, timezone="UTC")
        return CronTrigger.from_crontab(self.cron or "", timezone="UTC")


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    sources: dict[str, SourceSchedule]

    @classmethod
    def from_file(cls, path: Path = DEFAULT_SCHEDULE_PATH) -> "SchedulerConfig":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


async def run_scheduled_source(
    source_slug: str, *, runner_factory: RunnerFactory = CollectionRunner
) -> CollectionResult | None:
    try:
        result = await runner_factory().run(source_slug, trigger="scheduler")
    except Exception:
        LOGGER.exception("scheduled collection failed for source=%s", source_slug)
        return None
    LOGGER.info(
        "scheduled collection finished source=%s status=%s fetched=%s stored=%s",
        source_slug,
        result.status,
        result.fetched,
        result.inserted + result.updated,
    )
    return result


def register_jobs(
    scheduler: AsyncIOScheduler,
    config: SchedulerConfig,
    *,
    job_function: ScheduledCallable = run_scheduled_source,
) -> None:
    for source_slug, schedule in config.sources.items():
        if not schedule.enabled:
            continue
        job_id = f"collect:{source_slug}"
        if scheduler.get_job(job_id) is not None:
            scheduler.remove_job(job_id)
        scheduler.add_job(
            job_function,
            trigger=schedule.build_trigger(),
            args=[source_slug],
            id=job_id,
            name=f"Collect {source_slug}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )


def build_scheduler(config: SchedulerConfig | None = None) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    register_jobs(scheduler, config or SchedulerConfig.from_file())
    return scheduler


async def serve_scheduler(config_path: Path = DEFAULT_SCHEDULE_PATH) -> None:
    scheduler = build_scheduler(SchedulerConfig.from_file(config_path))
    scheduler.start()
    LOGGER.info("collection scheduler started with %s jobs", len(scheduler.get_jobs()))
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
