from collections.abc import Sequence

from app.analysis.schema import ArticleAnalysisInput
from app.research.models import (
    EvidenceCandidate,
    EvidenceDocument,
    EvidenceFailure,
    EvidenceOrigin,
    ResearchBundle,
)
from app.research.resolvers import (
    EvidenceResolutionError,
    EvidenceResolver,
    HttpEvidenceResolver,
)

MIN_DEEP_EVIDENCE_CHARACTERS = 2_000
MAX_EXTERNAL_DOCUMENTS = 3


class EvidenceResearchWorkflow:
    """Bounded, typed evidence acquisition before LLM analysis."""

    def __init__(self, resolver: EvidenceResolver | None = None) -> None:
        self.resolver = resolver or HttpEvidenceResolver()

    async def prepare(
        self,
        article: ArticleAnalysisInput,
        *,
        max_characters: int,
        timeout_seconds: float,
    ) -> tuple[ArticleAnalysisInput, ResearchBundle]:
        candidates = self._candidates(article)
        documents: list[EvidenceDocument] = []
        failures: list[EvidenceFailure] = []
        attempted: list[str] = []
        remaining = max(0, max_characters - len(article.content))

        if self._needs_primary_evidence(article):
            for candidate in candidates[:MAX_EXTERNAL_DOCUMENTS]:
                attempted.append(candidate.url)
                try:
                    document = await self.resolver.resolve(
                        candidate,
                        max_characters=max(500, remaining),
                        timeout_seconds=timeout_seconds,
                    )
                except EvidenceResolutionError as error:
                    failures.append(
                        EvidenceFailure(
                            url=candidate.url,
                            stage=error.stage,
                            reason=str(error)[:500],
                        )
                    )
                    continue
                documents.append(document)
                remaining = max(0, remaining - len(document.text))
                if self._enough(article.content, documents) or remaining == 0:
                    break

        extracted_characters = sum(len(document.text) for document in documents)
        coverage = (
            "strong"
            if self._enough(article.content, documents)
            else "partial"
            if documents
            else "thin"
        )
        bundle = ResearchBundle(
            documents=tuple(documents),
            failures=tuple(failures),
            attempted_urls=tuple(attempted),
            coverage=coverage,
            extracted_characters=extracted_characters,
        )
        return self._attach_bundle(article, bundle, max_characters), bundle

    @staticmethod
    def _candidates(article: ArticleAnalysisInput) -> list[EvidenceCandidate]:
        candidates = [
            EvidenceCandidate(
                url=url,
                origin=(
                    EvidenceOrigin.CANONICAL_URL
                    if index == 0
                    else EvidenceOrigin.SOURCE_URL
                ),
                priority=100 if url.casefold().endswith(".pdf") or "/blob/" in url else 50,
            )
            for index, url in enumerate(dict.fromkeys(article.source_urls))
            if url.startswith("https://")
        ]
        return sorted(candidates, key=lambda item: item.priority, reverse=True)

    @staticmethod
    def _needs_primary_evidence(article: ArticleAnalysisInput) -> bool:
        return len(article.content) < MIN_DEEP_EVIDENCE_CHARACTERS

    @staticmethod
    def _enough(stored_content: str, documents: Sequence[EvidenceDocument]) -> bool:
        return len(stored_content) + sum(
            len(document.text) for document in documents
        ) >= MIN_DEEP_EVIDENCE_CHARACTERS

    @staticmethod
    def _attach_bundle(
        article: ArticleAnalysisInput,
        bundle: ResearchBundle,
        max_characters: int,
    ) -> ArticleAnalysisInput:
        content = article.content
        for document in bundle.documents:
            header = (
                f"\n\n--- 外部证据文档｜{document.media_type}｜"
                f"{document.extractor}｜{document.url} ---\n"
            )
            available = max_characters - len(content) - len(header)
            if available <= 0:
                break
            content += header + document.text[:available]
        diagnostic = {
            "source": "evidence-research",
            "coverage": bundle.coverage,
            "attempted_urls": list(bundle.attempted_urls),
            "extracted_characters": bundle.extracted_characters,
            "documents": [
                {
                    "url": document.url,
                    "media_type": document.media_type,
                    "extractor": document.extractor,
                    "content_hash": document.content_hash,
                }
                for document in bundle.documents
            ],
            "failures": [
                {
                    "url": failure.url,
                    "stage": failure.stage,
                    "reason": failure.reason,
                }
                for failure in bundle.failures
            ],
        }
        return article.model_copy(
            update={
                "content": content[:max_characters],
                "source_context": [*article.source_context, diagnostic],
            }
        )
