from sqlalchemy.orm import Session

from app.models import Source
from app.sources.hugging_face.adapter import HuggingFaceAdapter
from app.sources.hugging_face.config import HuggingFaceConfig
from app.sources.persistence import PersistResult, ensure_source, persist_batch


def ensure_hugging_face_source(session: Session, config: HuggingFaceConfig) -> Source:
    return ensure_source(
        session,
        HuggingFaceAdapter.descriptor,
        config.persisted_config(),
    )


__all__ = ["PersistResult", "ensure_hugging_face_source", "persist_batch"]
