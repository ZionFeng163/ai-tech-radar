import asyncio
import hashlib

from app.analysis.schema import ArticleAnalysisInput
from app.research.models import EvidenceCandidate, EvidenceDocument
from app.research.passages import MAX_PASSAGE_CHARACTERS, build_evidence_passages
from app.research.resolvers import (
    EvidenceResolutionError,
    HtmlExtractor,
    _representative_page_indexes,
    canonical_document_url,
)
from app.research.workflow import EvidenceResearchWorkflow


class FakeResolver:
    def __init__(self, result: EvidenceDocument | EvidenceResolutionError) -> None:
        self.result = result
        self.urls: list[str] = []

    async def resolve(
        self,
        candidate: EvidenceCandidate,
        *,
        max_characters: int,
        timeout_seconds: float,
    ) -> EvidenceDocument:
        del max_characters, timeout_seconds
        self.urls.append(candidate.url)
        if isinstance(self.result, EvidenceResolutionError):
            raise self.result
        return self.result


def test_github_blob_is_a_url_transformer_not_a_special_workflow() -> None:
    assert canonical_document_url(
        "https://github.com/MoonshotAI/Kimi-K3/blob/main/k3_tech_report.pdf"
    ) == (
        "https://raw.githubusercontent.com/"
        "MoonshotAI/Kimi-K3/main/k3_tech_report.pdf"
    )


def test_pdf_sampling_keeps_opening_results_and_conclusion_pages() -> None:
    assert _representative_page_indexes(20) == [0, 1, 2, 3, 6, 13, 18, 19]


def test_html_extractor_drops_inline_footnote_superscripts() -> None:
    html = (
        b"<p>We should stop rampant <a href='/source'>smuggling</a>"
        b"<sup class='footnote'>3</sup> and workarounds.</p>"
    )

    text = HtmlExtractor().extract(html, max_characters=1_000)

    assert text == "We should stop rampant smuggling and workarounds."


def test_evidence_passages_are_bounded_stable_and_source_aware() -> None:
    article = ArticleAnalysisInput(
        title="A technical report",
        kind="paper",
        content=("First result. " * 100) + "\n\n[PDF page 2]\nSecond result.",
        source_urls=["https://example.com/report.pdf"],
        source_context=[{"source": "community", "score": 42}],
    )

    passages = build_evidence_passages(article)

    assert passages[0].id == "E001"
    assert passages[0].origin == "title"
    assert any(item.origin == "source_url" for item in passages)
    assert any(item.origin == "source_context" for item in passages)
    assert all(len(item.text) <= MAX_PASSAGE_CHARACTERS for item in passages)


def test_thin_article_acquires_primary_evidence_and_records_provenance() -> None:
    text = "Kimi-K3 technical report evidence. " * 100
    resolver = FakeResolver(
        EvidenceDocument(
            url="https://example.com/report.pdf",
            media_type="application/pdf",
            extractor="fake-pdf",
            text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
    )
    workflow = EvidenceResearchWorkflow(resolver=resolver)
    article = ArticleAnalysisInput(
        title="Kimi-K3 Technical Report",
        kind="news",
        content="Community discussion only.",
        source_urls=["https://example.com/report.pdf"],
    )

    enriched, bundle = asyncio.run(
        workflow.prepare(article, max_characters=12_000, timeout_seconds=5)
    )

    assert bundle.coverage == "strong"
    assert bundle.extracted_characters == len(text)
    assert "Kimi-K3 technical report evidence" in enriched.content
    assert enriched.source_context[-1]["source"] == "evidence-research"


def test_resolution_failure_becomes_diagnostic_state() -> None:
    resolver = FakeResolver(EvidenceResolutionError("download", "HTTP 503"))
    workflow = EvidenceResearchWorkflow(resolver=resolver)
    article = ArticleAnalysisInput(
        title="Thin report",
        kind="news",
        content="Community discussion only.",
        source_urls=["https://example.com/report.pdf"],
    )

    enriched, bundle = asyncio.run(
        workflow.prepare(article, max_characters=12_000, timeout_seconds=5)
    )

    assert bundle.coverage == "thin"
    assert bundle.failures[0].stage == "download"
    assert enriched.source_context[-1]["failures"][0]["reason"] == "HTTP 503"
