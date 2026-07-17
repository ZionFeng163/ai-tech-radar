from sqlalchemy.orm import Session

from app.models import Source
from app.sources.arxiv.adapter import ArxivAdapter
from app.sources.arxiv.config import ArxivConfig
from app.sources.persistence import PersistResult, ensure_source, persist_batch


def ensure_arxiv_source(session: Session, config: ArxivConfig) -> Source:
    return ensure_source(
        session,
        ArxivAdapter.descriptor,
        config.model_dump(mode="json"),
    )


__all__ = ["PersistResult", "ensure_arxiv_source", "persist_batch"]
