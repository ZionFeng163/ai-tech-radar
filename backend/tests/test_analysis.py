import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from app.analysis.config import DEFAULT_ANALYSIS_CONFIG_PATH, AnalysisConfig
from app.analysis.evaluation import evaluate, load_evaluation_samples
from app.analysis.pipeline import (
    AnalysisPipeline,
    _evidence_quote_found,
    _normalize_brief_language,
    _normalize_evidence,
    _normalize_temporal_framing,
    _validate_temporal_grounding,
    _validate_verified_facts,
)
from app.analysis.provider import (
    BailianChatProvider,
    LLMRequest,
    LLMResponse,
    OpenAIResponsesProvider,
    ProviderError,
)
from app.analysis.schema import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    ArticleAnalysisInput,
    ArticleAnalysisV1,
    ArticleBriefV1,
    OpenSourceStatus,
    TechnicalCategory,
    VerifiedFact,
    has_editorial_depth,
    strict_json_schema,
)


def _valid_output() -> ArticleAnalysisV1:
    return ArticleAnalysisV1(
        schema_version="1.0",
        technical_category=TechnicalCategory.INFERENCE,
        tags=["inference", "quantization"],
        summary_zh="该项目通过量化方法降低模型推理成本，并提供了可核查的实验与实现资料。",
        core_innovations=["在较低精度下保持推理质量"],
        differences_from_prior_work=["更重视部署阶段的延迟和显存占用"],
        application_scenarios=["在线模型服务与边缘设备部署"],
        open_source_status=OpenSourceStatus.OPEN,
        credibility_score=8,
        importance_score=7.5,
        why_it_matters="它可能降低高质量模型进入生产环境的硬件门槛。",
        verified_facts=[
            VerifiedFact(
                claim="项目提供开源运行时",
                evidence_quote="Open-source runtime",
            )
        ],
        technical_mechanism=["输入模型权重 → 执行量化 → 生成低精度运行时"],
        evidence_gaps=["缺少更多硬件上的延迟数据"],
        open_questions=["不同任务上的精度损失是多少？"],
        writing_angles=["判断｜量化降低部署门槛｜依据：开源运行时｜限制：缺少延迟数据"],
    )


def _request() -> LLMRequest:
    article = ArticleAnalysisInput(
        title="Quantized inference runtime",
        kind="release",
        content="Open-source runtime",
        license="Apache-2.0",
    )
    return LLMRequest("system", "user", article, strict_json_schema())


def test_default_production_config_uses_bailian_qwen() -> None:
    config = AnalysisConfig.from_file(DEFAULT_ANALYSIS_CONFIG_PATH)

    assert config.provider == "bailian"
    assert config.model == "qwen3.7-flash-2026-07-15"
    assert config.api_key_env == "DASHSCOPE_API_KEY"
    assert config.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_versioned_schema_rejects_extra_and_invalid_fields() -> None:
    schema = strict_json_schema()
    assert SCHEMA_VERSION == "1.0"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert "verified_facts" in schema["properties"]
    assert "technical_mechanism" in schema["properties"]
    assert "evidence_gaps" in schema["properties"]
    assert "writing_angles" in schema["properties"]

    payload = _valid_output().model_dump(mode="json") | {"unexpected": True}
    try:
        ArticleAnalysisV1.model_validate(payload)
    except ValidationError:
        pass
    else:
        raise AssertionError("extra fields must be rejected")


def test_verified_fact_quote_must_exist_in_source_material() -> None:
    output = _valid_output().model_copy(
        update={
            "verified_facts": [
                VerifiedFact(
                    claim="声称存在并未提供的性能数字",
                    evidence_quote="AREX-Base scored 99.9",
                )
            ]
        }
    )

    try:
        _validate_verified_facts(output, _request().article)
    except ValueError as exc:
        assert "evidence was not found" in str(exc)
    else:
        raise AssertionError("unquoted claims must fail grounding validation")


def test_legacy_deep_label_does_not_satisfy_editorial_depth() -> None:
    assert not has_editorial_depth({"depth": "deep", "core_innovations": ["旧栏目"]})
    assert has_editorial_depth(
        {
            "depth": "deep",
            "verified_facts": [{"claim": "事实", "evidence_quote": "source quote"}],
            "technical_mechanism": ["机制"],
            "evidence_gaps": ["缺口"],
            "open_questions": ["问题"],
            "writing_angles": ["角度"],
        }
    )


def test_evidence_quote_allows_only_nearby_ordered_omissions() -> None:
    corpus = _normalize_evidence(
        "<tr><td>AREX-Base</td><td>122B</td><td>85.9</td></tr>" + "x" * 900 + "99.9"
    )

    assert _evidence_quote_found("AREX-Base ... 85.9", corpus)
    assert not _evidence_quote_found("AREX-Base ... 99.9", corpus)


def test_evidence_quote_uses_nearby_duplicate_instead_of_first_distant_match() -> None:
    corpus = _normalize_evidence(
        "AREX-Base model family "
        + "x" * 900
        + "<tr><td>AREX-Base</td><td>122B</td><td>85.9</td></tr>"
    )

    assert _evidence_quote_found("AREX-Base ... 85.9", corpus)


def test_evidence_quote_ignores_json_field_wrappers() -> None:
    corpus = _normalize_evidence(
        json.dumps({"title": "Kimi-K3 Technical Report [pdf]"})
    )

    assert _evidence_quote_found('title: "Kimi-K3 Technical Report [pdf]"', corpus)


def test_analysis_rejects_historical_benchmark_as_current_frontier() -> None:
    output = _valid_output().model_copy(
        update={
            "summary_zh": (
                "项目方将 AREX 与 GPT-5.4 对比，并称其达到前沿闭源模型水平。"
            )
        }
    )

    try:
        _validate_temporal_grounding(output)
    except ValueError as exc:
        assert "时效表述" in str(exc)
    else:
        raise AssertionError("a dated benchmark must not become a current model ranking")


def test_analysis_allows_benchmark_framed_as_project_table() -> None:
    output = _valid_output().model_copy(
        update={
            "summary_zh": (
                "在项目方发布的评测表中，AREX 的 BrowseComp 得分高于 GPT-5.4。"
            )
        }
    )

    _validate_temporal_grounding(output)


def test_analysis_normalizes_stale_model_ranking_language() -> None:
    output = _valid_output().model_copy(
        update={
            "summary_zh": "项目方把 AREX 与 GPT-5.4 等前沿闭源模型进行了对比。",
            "novelty_summary": "它首次实现了开源模型对顶尖模型的赶超。",
        }
    )

    normalized = _normalize_temporal_framing(output)

    assert "前沿" not in normalized.summary_zh
    assert "闭源模型（项目方发布时的对照）" in normalized.summary_zh
    assert "首次实现" not in normalized.novelty_summary
    _validate_temporal_grounding(normalized)


def test_brief_removes_field_label_style_openings() -> None:
    output = ArticleBriefV1(
        schema_version="1.0",
        technical_category=TechnicalCategory.INFERENCE,
        signal_type="technical",
        tags=["inference"],
        summary_zh=(
            "新意在于把两个推理步骤合并，减少了一次重复计算并缩短响应时间，"
            "资料还提供了相同测试条件下的对照结果。"
        ),
        technical_overview="系统把原本分开的调度步骤合并执行，减少中间结果搬运。",
        novelty_summary="显著亮点：在相同测试条件下减少一次调度开销。",
        heat_reasons=["开发者可以直接观察响应延迟变化"],
        heat_score=6,
        open_source_status=OpenSourceStatus.OPEN,
        credibility_score=8,
        importance_score=7,
    )

    normalized = _normalize_brief_language(output)

    assert normalized.summary_zh.startswith("把两个推理步骤合并")
    assert normalized.novelty_summary.startswith("在相同测试条件下")


def test_committed_schema_and_human_evaluation_set_are_versioned() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (backend_root / "config" / "schemas" / "article-analysis-v1.json").read_text()
    )
    samples = load_evaluation_samples()

    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert len(samples) == 50
    assert all(sample.review_status == "human-reviewed" for sample in samples)


def test_offline_analysis_evaluation_meets_baseline() -> None:
    result = asyncio.run(evaluate(AnalysisConfig()))

    assert result.samples == 50
    assert result.schema_validity == 1
    assert result.category_accuracy >= 0.9
    assert result.open_source_accuracy >= 0.9
    assert result.importance_range_accuracy >= 0.9


def test_openai_provider_uses_responses_structured_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": _valid_output().model_dump_json()}
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIResponsesProvider(
        AnalysisConfig(provider="openai", model="gpt-5.6-sol"), client=client
    )
    response = asyncio.run(provider.analyze(_request()))
    asyncio.run(client.aclose())

    assert captured["model"] == "gpt-5.6-sol"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["name"] == SCHEMA_NAME
    assert captured["text"]["format"]["strict"] is True
    assert ArticleAnalysisV1.model_validate_json(response.output_text).importance_score == 7.5
    assert "resp_test" in response.raw_response


def test_openai_provider_preserves_raw_error_response(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": {"message": "bad schema"}})
        )
    )
    provider = OpenAIResponsesProvider(AnalysisConfig(provider="openai"), client=client)

    try:
        asyncio.run(provider.analyze(_request()))
    except ProviderError as exc:
        assert exc.retryable is False
        assert exc.raw_response is not None and "bad schema" in exc.raw_response
    else:
        raise AssertionError("HTTP errors must raise ProviderError")
    asyncio.run(client.aclose())


def test_bailian_provider_uses_json_mode_without_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "bailian_test",
                "choices": [
                    {"message": {"role": "assistant", "content": _valid_output().model_dump_json()}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BailianChatProvider(
        AnalysisConfig(
            provider="bailian",
            model="qwen3.7-flash-2026-07-15",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key_env="DASHSCOPE_API_KEY",
        ),
        client=client,
    )
    response = asyncio.run(provider.analyze(_request()))
    asyncio.run(client.aclose())

    assert captured["url"] == ("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    assert captured["model"] == "qwen3.7-flash-2026-07-15"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["enable_thinking"] is False
    assert "JSON Schema" in captured["messages"][1]["content"]
    assert ArticleAnalysisV1.model_validate_json(response.output_text).importance_score == 7.5
    assert "bailian_test" in response.raw_response


def test_bailian_provider_surfaces_quota_error_code(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403,
                json={
                    "error": {
                        "code": "AllocationQuota.FreeTierOnly",
                        "message": "Free quota exhausted.",
                    }
                },
            )
        )
    )
    provider = BailianChatProvider(
        AnalysisConfig(
            provider="bailian",
            model="qwen3.7-flash-2026-07-15",
            api_key_env="DASHSCOPE_API_KEY",
        ),
        client=client,
    )

    try:
        asyncio.run(provider.analyze(_request()))
    except ProviderError as exc:
        assert exc.retryable is False
        assert "AllocationQuota.FreeTierOnly" in str(exc)
        assert "Free quota exhausted" in str(exc)
        assert exc.raw_response is not None
    else:
        raise AssertionError("quota exhaustion must raise ProviderError")
    asyncio.run(client.aclose())


def test_pipeline_retries_invalid_output_and_retains_raw_attempt(monkeypatch) -> None:
    class FlakyProvider:
        name = "flaky"
        model = "test-model"
        calls = 0
        prompts: list[str] = []

        async def analyze(self, request: LLMRequest) -> LLMResponse:
            self.calls += 1
            self.prompts.append(request.user_prompt)
            if self.calls == 1:
                return LLMResponse(raw_response="raw-invalid", output_text='{"bad": true}')
            output = _valid_output().model_dump_json()
            return LLMResponse(raw_response=f"raw-success:{output}", output_text=output)

    provider = FlakyProvider()
    pipeline = AnalysisPipeline(
        AnalysisConfig(max_attempts=2, retry_backoff_seconds=0), provider=provider
    )
    request = _request()
    failed: list[tuple[str | None, str]] = []
    completed: list[str] = []
    async def build_request(article_id: UUID) -> LLMRequest:
        del article_id
        return request

    monkeypatch.setattr(pipeline, "_build_request", build_request)
    monkeypatch.setattr(pipeline, "_start_attempt", lambda article_id, value, attempt: uuid4())
    monkeypatch.setattr(
        pipeline,
        "_fail_attempt",
        lambda run_id, raw, error: failed.append((raw, error)),
    )
    monkeypatch.setattr(
        pipeline,
        "_complete_attempt",
        lambda article_id, run_id, raw, output: completed.append(raw),
    )

    succeeded, attempts = asyncio.run(pipeline._analyze_article(uuid4()))

    assert succeeded is True
    assert attempts == 2
    assert failed[0][0] == "raw-invalid"
    assert "validation failed" in failed[0][1]
    assert "上一次输出未通过后端证据校验" in provider.prompts[1]
    assert completed and completed[0].startswith("raw-success:")
