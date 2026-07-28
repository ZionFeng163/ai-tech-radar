import json
import re
from dataclasses import asdict, dataclass

from app.analysis.schema import ArticleAnalysisInput

MAX_PASSAGE_CHARACTERS = 800


@dataclass(frozen=True, slots=True)
class EvidencePassage:
    id: str
    origin: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def build_evidence_passages(article: ArticleAnalysisInput) -> list[EvidencePassage]:
    """Convert heterogeneous evidence into stable, independently verifiable passages."""

    raw_passages: list[tuple[str, str]] = [("title", article.title)]
    if article.license:
        raw_passages.append(("license", article.license))
    raw_passages.extend(("source_url", url) for url in article.source_urls)
    raw_passages.extend(("content", text) for text in _chunk_text(article.content))
    for context in article.source_context:
        if context.get("source") == "evidence-research":
            continue
        serialized = json.dumps(context, ensure_ascii=False, sort_keys=True)
        raw_passages.extend(("source_context", text) for text in _chunk_text(serialized))

    passages: list[EvidencePassage] = []
    seen: set[str] = set()
    for origin, text in raw_passages:
        normalized = " ".join(text.split()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        passages.append(
            EvidencePassage(
                id=f"E{len(passages) + 1:03d}",
                origin=origin,
                text=normalized,
            )
        )
    return passages


def _chunk_text(value: str) -> list[str]:
    chunks: list[str] = []
    for block in re.split(r"\n\s*\n|(?=\[PDF page \d+\])", value):
        remaining = block.strip()
        while remaining:
            if len(remaining) <= MAX_PASSAGE_CHARACTERS:
                chunks.append(remaining)
                break
            boundary = _preferred_boundary(remaining)
            chunks.append(remaining[:boundary].strip())
            remaining = remaining[boundary:].strip()
    return chunks


def _preferred_boundary(value: str) -> int:
    window = value[: MAX_PASSAGE_CHARACTERS + 1]
    minimum = MAX_PASSAGE_CHARACTERS // 2
    for pattern in (r"[。！？.!?]\s+", r"\n+", r"\s+"):
        matches = list(re.finditer(pattern, window))
        eligible = [match.end() for match in matches if match.end() >= minimum]
        if eligible:
            return eligible[-1]
    return MAX_PASSAGE_CHARACTERS
