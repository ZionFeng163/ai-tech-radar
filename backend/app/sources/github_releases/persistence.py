from sqlalchemy.orm import Session

from app.models import Source
from app.sources.github_releases.adapter import GitHubReleasesAdapter
from app.sources.github_releases.config import GitHubReleasesConfig
from app.sources.persistence import PersistResult, ensure_source, persist_batch


def ensure_github_releases_source(
    session: Session,
    config: GitHubReleasesConfig,
) -> Source:
    return ensure_source(
        session,
        GitHubReleasesAdapter.descriptor,
        config.persisted_config(),
    )


__all__ = ["PersistResult", "ensure_github_releases_source", "persist_batch"]
