import asyncio
import json

import httpx

from app.writing.config import DEFAULT_WRITING_CONFIG_PATH, WritingConfig
from app.writing.provider import BailianWritingProvider
from app.writing.schema import WritingAngleSet, WritingReview
from app.writing.service import (
    WritingService,
    _validate_automatic_review,
    _validate_draft_format,
)


def test_writing_config_uses_separate_qwen_pipeline() -> None:
    config = WritingConfig.from_file(DEFAULT_WRITING_CONFIG_PATH)

    assert config.provider == "bailian"
    assert config.model == "qwen3.7-plus-2026-05-26"
    assert config.prompt_version == "writing-studio-v4-public-readable"
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


def test_angle_schema_allows_one_grounded_angle_for_thin_sources() -> None:
    schema = WritingAngleSet.model_json_schema()

    assert schema["properties"]["angles"]["minItems"] == 1
    assert schema["properties"]["angles"]["maxItems"] == 3
