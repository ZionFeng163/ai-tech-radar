import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.sources.base import SourceAdapter, SourceDescriptor
from app.sources.dev_community import DevCommunityAdapter
from app.sources.hacker_news import HackerNewsAdapter
from app.sources.hugging_face import HuggingFaceAdapter, HuggingFaceConfig
from app.sources.hugging_face_papers import (
    HuggingFacePapersAdapter,
    HuggingFacePapersConfig,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
HUGGING_FACE_CONFIG_PATH = BACKEND_ROOT / "config" / "sources" / "hugging-face.json"
HUGGING_FACE_PAPERS_CONFIG_PATH = (
    BACKEND_ROOT / "config" / "sources" / "hugging-face-papers.json"
)


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    descriptor: SourceDescriptor
    persisted_config: dict[str, object]
    page_size: int
    adapter_factory: Callable[[], SourceAdapter]


def _hugging_face_source() -> RegisteredSource:
    config = (
        HuggingFaceConfig.from_file(HUGGING_FACE_CONFIG_PATH)
        if HUGGING_FACE_CONFIG_PATH.exists()
        else HuggingFaceConfig()
    )
    if token := os.getenv("HF_TOKEN"):
        config = HuggingFaceConfig.model_validate({**config.model_dump(), "token": token})
    return RegisteredSource(
        descriptor=HuggingFaceAdapter.descriptor,
        persisted_config=config.persisted_config(),
        page_size=config.page_size,
        adapter_factory=lambda: HuggingFaceAdapter(config),
    )


def _hugging_face_papers_source() -> RegisteredSource:
    config = (
        HuggingFacePapersConfig.from_file(HUGGING_FACE_PAPERS_CONFIG_PATH)
        if HUGGING_FACE_PAPERS_CONFIG_PATH.exists()
        else HuggingFacePapersConfig()
    )
    if token := os.getenv("HF_TOKEN"):
        config = HuggingFacePapersConfig.model_validate(
            {**config.model_dump(), "token": token}
        )
    return RegisteredSource(
        descriptor=HuggingFacePapersAdapter.descriptor,
        persisted_config=config.persisted_config(),
        page_size=config.page_size,
        adapter_factory=lambda: HuggingFacePapersAdapter(config),
    )


def _hacker_news_source() -> RegisteredSource:
    return RegisteredSource(
        descriptor=HackerNewsAdapter.descriptor,
        persisted_config={"feed": "topstories", "curation": "community-ranked"},
        page_size=30,
        adapter_factory=HackerNewsAdapter,
    )


def _dev_community_source() -> RegisteredSource:
    return RegisteredSource(
        descriptor=DevCommunityAdapter.descriptor,
        persisted_config={"window_days": 7, "curation": "popularity-ranked"},
        page_size=20,
        adapter_factory=DevCommunityAdapter,
    )


class SourceRegistry:
    def __init__(self, sources: list[RegisteredSource] | None = None) -> None:
        registered = sources or [
            _hacker_news_source(),
            _hugging_face_source(),
            _hugging_face_papers_source(),
            _dev_community_source(),
        ]
        self._sources = {source.descriptor.slug: source for source in registered}

    @property
    def slugs(self) -> tuple[str, ...]:
        return tuple(self._sources)

    def get(self, source_slug: str) -> RegisteredSource:
        try:
            return self._sources[source_slug]
        except KeyError as error:
            available = ", ".join(self.slugs)
            raise ValueError(
                f"unknown source {source_slug!r}; choose one of: {available}"
            ) from error
