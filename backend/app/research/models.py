from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EvidenceOrigin(StrEnum):
    STORED_CONTENT = "stored_content"
    CANONICAL_URL = "canonical_url"
    SOURCE_URL = "source_url"
    DISCOVERED_LINK = "discovered_link"


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    url: str
    origin: EvidenceOrigin
    priority: int = 0


@dataclass(frozen=True, slots=True)
class EvidenceDocument:
    url: str
    media_type: str
    extractor: str
    text: str
    content_hash: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class EvidenceFailure:
    url: str
    stage: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResearchBundle:
    documents: tuple[EvidenceDocument, ...]
    failures: tuple[EvidenceFailure, ...]
    attempted_urls: tuple[str, ...]
    coverage: str
    extracted_characters: int

    @property
    def has_primary_document(self) -> bool:
        return bool(self.documents)
