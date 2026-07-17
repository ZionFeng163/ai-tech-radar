import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.sources.arxiv import ArxivAdapter, ArxivConfig
from app.sources.base import SourceAdapter, SourceDescriptor
from app.sources.github_releases import GitHubReleasesAdapter, GitHubReleasesConfig
from app.sources.hugging_face import HuggingFaceAdapter, HuggingFaceConfig

BACKEND_ROOT = Path(__file__).resolve().parents[2]
GITHUB_CONFIG_PATH = BACKEND_ROOT / "config" / "sources" / "github-releases.json"
HUGGING_FACE_CONFIG_PATH = BACKEND_ROOT / "config" / "sources" / "hugging-face.json"


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    descriptor: SourceDescriptor
    persisted_config: dict[str, object]
    page_size: int
    adapter_factory: Callable[[], SourceAdapter]


def _arxiv_source() -> RegisteredSource:
    config = ArxivConfig()
    return RegisteredSource(
        descriptor=ArxivAdapter.descriptor,
        persisted_config=config.model_dump(mode="json"),
        page_size=config.page_size,
        adapter_factory=lambda: ArxivAdapter(config),
    )


def _github_source() -> RegisteredSource:
    config = (
        GitHubReleasesConfig.from_file(GITHUB_CONFIG_PATH)
        if GITHUB_CONFIG_PATH.exists()
        else GitHubReleasesConfig()
    )
    if token := os.getenv("GITHUB_TOKEN"):
        config = GitHubReleasesConfig.model_validate({**config.model_dump(), "token": token})
    return RegisteredSource(
        descriptor=GitHubReleasesAdapter.descriptor,
        persisted_config=config.persisted_config(),
        page_size=config.page_size,
        adapter_factory=lambda: GitHubReleasesAdapter(config),
    )


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


class SourceRegistry:
    def __init__(self, sources: list[RegisteredSource] | None = None) -> None:
        registered = sources or [_arxiv_source(), _github_source(), _hugging_face_source()]
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
