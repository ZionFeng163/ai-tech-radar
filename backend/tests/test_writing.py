import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.writing.config import DEFAULT_WRITING_CONFIG_PATH, WritingConfig
from app.writing.provider import BailianWritingProvider, WritingResponse
from app.writing.schema import HumanInput, WritingAngle, WritingAngleSet, WritingReview
from app.writing.service import (
    WritingService,
    _validate_angle_set,
    _validate_automatic_review,
    _validate_draft_format,
)


def test_writing_config_uses_separate_qwen_pipeline() -> None:
    config = WritingConfig.from_file(DEFAULT_WRITING_CONFIG_PATH)

    assert config.provider == "bailian"
    assert config.model == "qwen3.7-flash-2026-07-15"
    assert config.prompt_version == "writing-studio-v5-readable-freshness"
    assert config.max_output_tokens > 2_000


def test_writing_requires_completed_deep_analysis() -> None:
    try:
        WritingService._require_deep_analysis({"analysis_depth": "brief"})
    except ValueError as exc:
        assert "先完成深度分析" in str(exc)
    else:
        raise AssertionError("writing must be gated by deep analysis")

    WritingService._require_deep_analysis({"analysis_depth": "deep"})


def test_writing_provider_only_enables_json_mode_for_structured_stages(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "draft"}}]},
        )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BailianWritingProvider(WritingConfig(), client=client)

    asyncio.run(provider.complete("system", "user"))
    asyncio.run(provider.complete("system", "user", json_schema={"type": "object"}))
    asyncio.run(client.aclose())

    assert "response_format" not in captured[0]
    assert captured[1]["response_format"] == {"type": "json_object"}
    assert captured[0]["enable_thinking"] is False


def test_thread_format_rejects_oversized_or_wrong_post_count() -> None:
    valid = "\n\n".join(f"{index}/4 " + "观点" * 20 for index in range(1, 5))
    _validate_draft_format(valid, "thread")

    too_long = "\n\n".join(["1/4 " + "长" * 281, "2/4 ok", "3/4 ok", "4/4 ok"])
    try:
        _validate_draft_format(too_long, "thread")
    except ValueError as exc:
        assert "超过 280" in str(exc)
    else:
        raise AssertionError("oversized posts must be rejected")

    try:
        _validate_draft_format("1/2 one\n\n2/2 two", "thread")
    except ValueError as exc:
        assert "4–6" in str(exc)
    else:
        raise AssertionError("short threads must be rejected")


def test_reference_style_post_allows_the_requested_medium_length() -> None:
    _validate_draft_format("一段具体的观点。" * 35, "short_post")

    try:
        _validate_draft_format("太长了" * 121, "short_post")
    except ValueError as exc:
        assert "超过 360" in str(exc)
    else:
        raise AssertionError("overlong point-of-view posts must be rejected")


def test_reference_style_post_rejects_too_many_paragraphs() -> None:
    try:
        _validate_draft_format("\n\n".join(["新信息"] * 6), "short_post")
    except ValueError as exc:
        assert "最多 5 个" in str(exc)
    else:
        raise AssertionError("mechanical multi-paragraph posts must be compressed")


def test_metadata_only_post_has_stricter_size_budget() -> None:
    try:
        _validate_draft_format(
            "只有标题复述。",
            "short_post",
            short_post_min=110,
            short_post_max=280,
            short_post_paragraphs=3,
        )
    except ValueError as exc:
        assert "少于 110" in str(exc)
    else:
        raise AssertionError("thin posts must still contain an editorial idea")

    try:
        _validate_draft_format(
            "还是很长" * 71,
            "short_post",
            short_post_max=280,
            short_post_paragraphs=3,
        )
    except ValueError as exc:
        assert "超过 280" in str(exc)
    else:
        raise AssertionError("thin sources must produce shorter posts")

    try:
        _validate_draft_format(
            "资料里只有标题和元数据，所以只能猜测技术债。",
            "short_post",
            short_post_max=280,
            short_post_paragraphs=3,
        )
    except ValueError as exc:
        assert "模板化表达" in str(exc)
    else:
        raise AssertionError("internal source limitations must not leak into the post")


def test_reference_style_rejects_known_report_phrases() -> None:
    try:
        _validate_draft_format("这项发布释放了一个明确信号。", "short_post")
    except ValueError as exc:
        assert "模板化表达" in str(exc)
    else:
        raise AssertionError("report-style filler must trigger one rewrite")


def test_reference_style_rejects_abstract_ai_diagnosis() -> None:
    try:
        _validate_draft_format(
            "评论很多，恰恰说明大家都陷入集体焦虑，系统熵增成为新的瓶颈。",
            "short_post",
        )
    except ValueError as exc:
        assert "模板化表达" in str(exc)
    else:
        raise AssertionError("abstract AI diagnosis must trigger a rewrite")


def test_short_post_rejects_excessive_jargon_density() -> None:
    try:
        _validate_draft_format(
            "AREX 基于 Qwen MoE，通过 NIM 和 NVFP4 运行，并在 QCalEval 上测试。",
            "short_post",
        )
    except ValueError as exc:
        assert "过多英文术语" in str(exc)
    else:
        raise AssertionError("short posts must translate rather than stack jargon")


def test_short_post_rejects_colloquial_overclaiming() -> None:
    try:
        _validate_draft_format(
            "这证明低精度已经把量子校准这块硬骨头都能啃下来。",
            "short_post",
        )
    except ValueError as exc:
        assert "模板化表达" in str(exc)
    else:
        raise AssertionError("plain language must not strengthen unsupported claims")


def test_automatic_review_blocks_low_public_accessibility() -> None:
    review = WritingReview(
        verdict="术语过密，需要改写",
        thesis_clarity=8,
        originality=8,
        technical_clarity=8,
        accessibility=5,
        human_voice=7,
        issues=[],
        strongest_line="",
        cut_suggestions=[],
    )

    try:
        _validate_automatic_review(review)
    except ValueError as exc:
        assert "公众可读性" in str(exc)
    else:
        raise AssertionError("drafts with low accessibility must be rewritten")


def test_thread_is_preserved_when_automatic_review_has_blocking_warning(
    monkeypatch,
) -> None:
    draft = "\n\n".join(
        [
            "1/4 Kimi K3 这次值得看的，不只是参数变大。",
            "2/4 它尝试用混合注意力降低长上下文的计算负担。",
            "3/4 但项目方的模型对比，只能代表发布时的测试结果。",
            "4/4 真正值得继续看的是，开放权重后这些能力能否被复现。",
        ]
    )
    review = WritingReview(
        verdict="草稿可读，但模型版本需要增加时间限定。",
        thesis_clarity=8,
        originality=7,
        technical_clarity=8,
        accessibility=8,
        human_voice=8,
        issues=[
            {
                "category": "fact",
                "severity": "high",
                "quote": "项目方的模型对比",
                "problem": "模型排名只能代表发布时的评测。",
                "suggestion": "明确写成项目方发布时的测试结果。",
            }
        ],
        strongest_line="不只是参数变大。",
        cut_suggestions=[],
    )

    class FakeProvider:
        name = "fake"
        model = "fake-model"

        async def complete(
            self,
            system_prompt: str,
            user_prompt: str,
            *,
            json_schema: dict[str, object] | None = None,
        ) -> WritingResponse:
            del system_prompt, user_prompt
            output = review.model_dump_json() if json_schema else draft
            return WritingResponse(output_text=output, raw_response=output)

    class FakeSession:
        def commit(self) -> None:
            pass

        def refresh(self, project: object) -> None:
            del project

    project = SimpleNamespace(
        article_id=uuid4(),
        angle_options=[_angle().model_dump(mode="json")],
        selected_angle_id=None,
        output_format="short_post",
        human_input={},
        draft_content=None,
        review={},
        status="angles_ready",
        provider=None,
        model=None,
        prompt_version=None,
        error_summary=None,
    )
    service = WritingService(WritingConfig(), provider=FakeProvider())
    monkeypatch.setattr(service, "get", lambda session, project_id: project)
    monkeypatch.setattr(
        service,
        "_source_pack",
        lambda session, article_id: {
            "analysis_depth": "deep",
            "source_quality": "source_excerpt",
        },
    )

    result = asyncio.run(
        service.generate_draft(
            FakeSession(),  # type: ignore[arg-type]
            uuid4(),
            angle_id="technical",
            output_format="thread",
            human_input=HumanInput(),
        )
    )

    assert result.draft_content == draft
    assert result.output_format == "thread"
    assert result.status == "draft_ready"
    assert result.review["issues"][0]["severity"] == "high"
    assert "自动审校发现阻断问题" in result.error_summary


def test_angle_schema_allows_one_grounded_angle_for_thin_sources() -> None:
    schema = WritingAngleSet.model_json_schema()

    assert schema["properties"]["angles"]["minItems"] == 1
    assert schema["properties"]["angles"]["maxItems"] == 3


def _angle(**overrides: object) -> WritingAngle:
    values: dict[str, object] = {
        "id": "technical",
        "label": "少走回头路",
        "thesis": "它会记住哪些资料已经确认、哪些线索走不通，研究越久越不容易绕回原路。",
        "signal": "长时间研究时减少重复搜索。",
        "mechanism": "模型更新内部研究状态。",
        "change": "保留有效线索并跳过已否定路径。",
        "tension": "",
        "evidence": ["原文说明它会保留和拒绝候选线索。"],
        "counterargument": "",
        "uncertainty": "",
        "reader_gain": "看懂这个 Agent 为什么能连续查资料而不总是从头再来。",
        "recommended_format": "short_post",
        "value_score": 8,
    }
    values.update(overrides)
    return WritingAngle.model_validate(values)


def test_angle_rejects_internal_interface_language_in_public_fields() -> None:
    angle_set = WritingAngleSet(
        angles=[
            _angle(
                thesis=(
                    "AREX 通过 update_context 显式维护已验证发现、"
                    "被拒候选项和未决约束，避免重复探索无效路径。"
                )
            )
        ]
    )

    try:
        _validate_angle_set(
            angle_set,
            {"title": "AREX", "source_excerpt": "The model invokes update_context."},
        )
    except ValueError as exc:
        assert "实际作用" in str(exc) or "研究报告" in str(exc)
    else:
        raise AssertionError("internal state vocabulary must be translated for readers")


def test_angle_rejects_stale_benchmark_as_current_frontier() -> None:
    angle_set = WritingAngleSet(
        angles=[
            _angle(
                label="超越闭源前沿",
                thesis="AREX 在项目表格里超过 GPT-5.4，说明它已经超越闭源前沿。",
            )
        ]
    )

    try:
        _validate_angle_set(
            angle_set,
            {"title": "AREX", "source_excerpt": "GPT-5.4 82.7; AREX 85.9"},
        )
    except ValueError as exc:
        assert "当前市场判断" in str(exc)
    else:
        raise AssertionError("historical benchmark must not be framed as current frontier")


def test_angle_rejects_model_version_missing_from_original_source() -> None:
    angle_set = WritingAngleSet(
        angles=[
            _angle(thesis="AREX 在项目方的测试表中超过了 GPT-5.6。")
        ]
    )

    try:
        _validate_angle_set(
            angle_set,
            {"title": "AREX", "source_excerpt": "GPT-5.4 82.7; AREX 85.9"},
        )
    except ValueError as exc:
        assert "原始资料没有" in str(exc)
    else:
        raise AssertionError("the writer must not silently update model versions")
