import asyncio

import httpx

from app.composer.service import ComposerService, extract_arxiv_id, validate_composer_draft
from app.writing.config import WritingConfig
from app.writing.provider import WritingResponse

ATOM_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>1</opensearch:itemsPerPage>
  <entry>
    <id>https://arxiv.org/abs/2607.08662v1</id>
    <updated>2026-07-12T00:00:00Z</updated>
    <published>2026-07-12T00:00:00Z</published>
    <title>WebSwarm: Dynamic Multi-Agent Search</title>
    <summary>
      WebSwarm organizes search agents dynamically as evidence arrives.
      On BrowseComp-Plus accuracy improves from 50.5 to 68.0, while
      DeepWideSearch Item F1 improves from 46.63 to 58.40.
    </summary>
    <author><name>Alice Example</name></author>
    <category term="cs.AI" />
    <link href="https://arxiv.org/abs/2607.08662v1" rel="alternate" type="text/html" />
  </entry>
</feed>
"""


class FakeWritingProvider:
    name = "fake"
    model = "fake-writer"

    def __init__(self, output: str) -> None:
        self.output = output
        self.prompts: list[tuple[str, str]] = []

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_schema: dict[str, object] | None = None,
    ) -> WritingResponse:
        assert json_schema is None
        self.prompts.append((system_prompt, user_prompt))
        return WritingResponse(output_text=self.output, raw_response="{}")


def test_extract_arxiv_id_accepts_abs_pdf_and_prefixed_values() -> None:
    assert extract_arxiv_id("https://arxiv.org/abs/2607.08662") == "2607.08662"
    assert extract_arxiv_id("https://arxiv.org/pdf/2607.08662v2.pdf") == "2607.08662v2"
    assert extract_arxiv_id("arXiv:2607.08662") == "2607.08662"

    try:
        extract_arxiv_id("https://example.com/2607.08662")
    except ValueError as exc:
        assert "只支持 arXiv" in str(exc)
    else:
        raise AssertionError("non-arXiv URLs must be rejected")


def test_paper_composer_reads_official_feed_and_appends_canonical_link() -> None:
    body = "\n\n".join(
        [
            "复杂搜索同时需要深挖和广搜时，提前固定分工很容易失效。",
            "WebSwarm 让搜索节点随着证据出现再决定继续展开、调整方向或汇总结果。",
            "每个节点只处理当前目标，也可以创建新的子节点；前面找到的可靠来源和无效路径会传给后续节点，减少重复搜索。",
            (
                "摘要报告，在 BrowseComp-Plus 上准确率从 50.5 提升到 68.0，"
                "DeepWideSearch 的 Item F1 从 46.63 提升到 58.40。"
            ),
            "这项工作的启发是，复杂问题的结构往往要看到中间证据后才会显现。搜索系统不仅要找答案，也要在过程中重新决定由谁继续找。",
        ]
    )
    provider = FakeWritingProvider(body)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id_list"] == "2607.08662"
        return httpx.Response(200, content=ATOM_FEED)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ComposerService(
        WritingConfig(),
        provider=provider,
        arxiv_client=client,
    )
    result = asyncio.run(
        service.compose_paper("https://arxiv.org/abs/2607.08662")
    )
    asyncio.run(client.aclose())

    assert result.mode == "paper"
    assert result.source is not None
    assert result.source.title == "WebSwarm: Dynamic Multi-Agent Search"
    assert result.draft.endswith("📎 arXiv: https://arxiv.org/abs/2607.08662v1")
    assert "50.5" in provider.prompts[0][1]


def test_paper_composer_falls_back_to_official_abstract_page_after_rate_limit() -> None:
    body = "论文搜索的任务结构不能总在开始前确定。" * 30
    provider = FakeWritingProvider(body)
    requests: list[str] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.host == "export.arxiv.org":
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(
            200,
            text=(
                '<html><head><meta name="citation_title" content="WebSwarm">'
                '<meta name="citation_author" content="Alice Example">'
                '<meta name="citation_abstract" content="Dynamic search agents improve '
                'BrowseComp-Plus accuracy from 50.5 to 68.0.">'
                '<meta name="citation_date" content="2026/07/12"></head></html>'
            ),
        )

    async def sleep(delay: float) -> None:
        delays.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ComposerService(
        WritingConfig(),
        provider=provider,
        arxiv_client=client,
        sleep=sleep,
    )
    result = asyncio.run(service.compose_paper("2607.08662"))
    asyncio.run(client.aclose())

    assert requests == ["/api/query", "/api/query", "/abs/2607.08662"]
    assert delays == [1.0]
    assert result.source is not None
    assert result.source.title == "WebSwarm"
    assert "50.5" in provider.prompts[0][1]


def test_idea_composer_does_not_require_or_store_a_source() -> None:
    draft = (
        "AI 编程把写代码变便宜了，但没有自动让软件更容易维护。"
        "当生成速度越来越快，真正稀缺的可能变成理解代码、审查边界和承担长期责任的人。\n\n"
        "所以衡量这类工具，不能只看一天写了多少行，还要看半年后有没有人敢继续改。"
    )
    provider = FakeWritingProvider(draft)
    service = ComposerService(WritingConfig(), provider=provider)

    result = asyncio.run(service.compose_idea("代码更快，但维护可能更贵，不能只看行数。"))

    assert result.mode == "idea"
    assert result.source is None
    assert result.draft == draft


def test_composer_rejects_template_language() -> None:
    try:
        validate_composer_draft(
            "值得关注的是，AI 编程释放了一个信号。" * 8,
            "idea",
        )
    except ValueError as exc:
        assert "模板化表达" in str(exc)
    else:
        raise AssertionError("template-like composer output must be rejected")
