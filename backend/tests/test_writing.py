import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.writing.config import DEFAULT_WRITING_CONFIG_PATH, WritingConfig
from app.writing.provider import BailianWritingProvider, WritingResponse
from app.writing.schema import (
    ClaimAudit,
    HumanInput,
    VerifiedWriting,
    WritingAngle,
    WritingAngleSet,
    WritingReview,
)
from app.writing.service import (
    WritingService,
    _validate_angle_set,
    _validate_automatic_review,
    _validate_claim_audit,
    _validate_draft_format,
    _writing_style_profile,
)


def test_writing_config_uses_separate_qwen_pipeline() -> None:
    config = WritingConfig.from_file(DEFAULT_WRITING_CONFIG_PATH)

    assert config.provider == "bailian"
    assert config.model == "qwen3.7-flash-2026-07-15"
    assert config.prompt_version == "writing-studio-v9-verified-claims"
    assert config.max_output_tokens > 2_000


def test_writing_skill_loads_references_by_stage() -> None:
    config = WritingConfig.from_file(DEFAULT_WRITING_CONFIG_PATH)

    angles = config.load_skill("angles")
    draft = config.load_skill("draft")
    review = config.load_skill("review")
    verification = config.load_skill("verification")

    assert "Tech Social Writer" in angles
    assert "作者声音档案" in angles
    assert "中文成稿修补" not in angles
    assert "中文成稿修补" in draft
    assert "独立事实核验" not in draft
    assert "独立事实核验" in review
    assert "独立事实核验" in verification


def test_writing_style_routes_technical_documents_without_affecting_news() -> None:
    assert (
        _writing_style_profile(
            "paper",
            source_quality="source_excerpt",
            source_urls=["https://huggingface.co/papers/2607.24653"],
        )
        == "technical_reading_notes"
    )
    assert (
        _writing_style_profile(
            "news",
            source_quality="metadata_only",
            source_urls=[
                "https://github.com/example/report/blob/main/technical-report.pdf"
            ],
        )
        == "technical_findings"
    )
    assert (
        _writing_style_profile(
            "news",
            source_quality="source_excerpt",
            source_urls=[
                "https://www.anthropic.com/news/our-position-on-open-weights-models"
            ],
        )
        == "editorial_commentary"
    )


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
    valid = "\n\n".join(
        f"{index}/4 " + f"第{index}条提供不同的事实、机制解释或限制。" * 7
        for index in range(1, 5)
    )
    _validate_draft_format(valid, "thread")

    too_long = "\n\n".join(
        [
            "1/4 " + "长" * 281,
            "2/4 " + "有效信息" * 30,
            "3/4 " + "不同解释" * 30,
            "4/4 " + "实际限制" * 30,
        ]
    )
    try:
        _validate_draft_format(too_long, "thread")
    except ValueError as exc:
        assert "超过 280" in str(exc)
    else:
        raise AssertionError("oversized posts must be rejected")

    try:
        _validate_draft_format("1/2 " + "内容" * 60 + "\n\n2/2 " + "内容" * 60, "thread")
    except ValueError as exc:
        assert "3–4" in str(exc)
    else:
        raise AssertionError("short threads must be rejected")


def test_thread_rejects_mechanical_short_fragments() -> None:
    fragments = "\n\n".join(
        f"{index}/4 " + "只有一句很短的话。" * 3 for index in range(1, 5)
    )

    try:
        _validate_draft_format(fragments, "thread")
    except ValueError as exc:
        assert "少于 90" in str(exc) or "至少 420" in str(exc)
    else:
        raise AssertionError("a thread must contain more substance than a split short post")


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
            (
                "AREX 基于 Qwen MoE，通过 NIM、NVFP4、DSP 和 API 运行，"
                "并在 QCalEval 上测试。"
            ),
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


def test_unsafe_verification_preserves_draft_without_exposing_final_content(
    monkeypatch,
) -> None:
    draft = "\n\n".join(
        [
            (
                "1/4 Kimi K3 这次值得看的不只是参数变大。它用混合专家架构"
                "只激活部分参数，尝试在扩大模型容量的同时控制每次推理真正参与计算"
                "的规模。这项取舍直接影响部署时需要承担的计算量，也决定大模型能否"
                "被更多团队实际使用。"
            ),
            (
                "2/4 它还把两类注意力组合起来处理长上下文：大部分层优先考虑"
                "计算效率，少量全局注意力负责保留远距离信息。价值在于机制组合，"
                "而不是单个新名词。真正需要比较的是，同样长度下它是否更快、更稳，"
                "以及会损失多少信息。"
            ),
            (
                "3/4 项目方给出的模型对比只能代表发布时的测试结果，不能直接变成"
                "今天的市场排名。真正需要继续验证的是，百万上下文在真实任务中的"
                "稳定性和成本。基准成绩可以说明方向，但不能代替长时间运行时的"
                "失败率、延迟和显存数据。"
            ),
            (
                "4/4 完整权重开放后，外部团队终于可以检查训练结论能否复现。"
                "对开发者来说，这比一句“追上闭源”更有价值：能力、部署代价和失败"
                "场景都能被实际检验。如果第三方复现与报告一致，这套架构才可能成为"
                "后续项目可以采用的工程基线。"
            ),
        ]
    )
    review = WritingReview(
        verdict="已删除无法核实的版本判断，正文可以继续编辑。",
        thesis_clarity=8,
        originality=7,
        technical_clarity=8,
        accessibility=8,
        human_voice=8,
        issues=[],
        strongest_line="不只是参数变大。",
        cut_suggestions=[],
    )
    verified = VerifiedWriting(
        final_content=draft,
        changes=["限定评测发生在项目发布时。"],
    )
    audit = ClaimAudit(
        publishable=False,
        summary="仍有一句性能结论没有原文证据。",
        claims=[
            {
                "claim": "这项取舍直接影响部署时需要承担的计算量",
                "kind": "causal",
                "support_status": "unsupported",
                "risk": "high",
                "evidence_quote": "",
                "evidence_location": "",
                "reason": "资料没有给出部署计算量对照。",
            }
        ],
        review=review,
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
            if json_schema is None:
                output = draft
            elif json_schema.get("title") == "VerifiedWriting":
                output = verified.model_dump_json()
            else:
                output = audit.model_dump_json()
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
        claim_ledger=[],
        verification={},
        final_content=None,
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
            "source_excerpt": "Kimi K3 technical report.",
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
    assert result.status == "verification_failed"
    assert result.final_content is None
    assert result.claim_ledger == []
    assert "未获证据支持" in result.error_summary


def test_claim_audit_requires_exact_evidence_and_covers_numbers() -> None:
    content = "项目方在 BrowseComp 测试中报告，准确率从 45.9 提升到 54.8。"
    source_pack = {
        "source_excerpt": (
            "On BrowseComp, accuracy improved from 45.9 to 54.8."
        )
    }
    audit = ClaimAudit(
        publishable=True,
        summary="数字、对象和方向均可追溯。",
        claims=[
            {
                "claim": "在 BrowseComp 测试中报告，准确率从 45.9 提升到 54.8",
                "kind": "metric",
                "support_status": "supported",
                "risk": "high",
                "evidence_quote": (
                    "On BrowseComp, accuracy improved from 45.9 to 54.8."
                ),
                "evidence_location": "E1",
                "reason": "原文直接给出测试名、指标和前后数值。",
            }
        ],
        review=_publishable_review(),
    )

    _validate_claim_audit(audit, source_pack, content)


def test_successful_verification_stores_bounded_publishable_content(
    monkeypatch,
) -> None:
    draft = (
        "StateAct 在这组长程任务里只让主智能体在 1.1% 的步骤调用视觉模块。"
        "\n\n其余步骤直接读取文件和网页结构，减少反复看截图的成本。"
    )
    final = (
        "StateAct 在论文这组长程任务里，只让主智能体在 1.1% 的步骤调用视觉模块。"
        "\n\n其余步骤直接读取文件和网页结构。这个结果只说明论文测试里的调用方式，"
        "不能直接推成所有自动化任务都更便宜。"
    )
    review = WritingReview(
        verdict="范围已经限定，技术事实与作者判断能够区分。",
        thesis_clarity=9,
        originality=8,
        technical_clarity=9,
        accessibility=9,
        human_voice=8,
        issues=[],
        strongest_line="不能直接推成所有自动化任务都更便宜。",
        cut_suggestions=[],
    )
    verified = VerifiedWriting(
        final_content=final,
        changes=["把结果限定为论文测试，删除普遍降本结论。"],
    )
    audit = ClaimAudit(
        publishable=True,
        summary="事实有原文证据，外推边界已明确。",
        claims=[
            {
                "claim": "在论文这组长程任务里，只让主智能体在 1.1% 的步骤调用视觉模块",
                "kind": "metric",
                "support_status": "supported",
                "risk": "high",
                "evidence_quote": (
                    "Only 1.1% of main-agent steps use the GUI subagent."
                ),
                "evidence_location": "E1",
                "reason": "原文直接给出调用比例和对象。",
            },
            {
                "claim": "其余步骤直接读取文件和网页结构",
                "kind": "fact",
                "support_status": "supported",
                "risk": "medium",
                "evidence_quote": "reads files and DOM structures directly",
                "evidence_location": "E2",
                "reason": "原文直接说明非视觉步骤读取的状态。",
            },
            {
                "claim": "不能直接推成所有自动化任务都更便宜",
                "kind": "opinion",
                "support_status": "inference",
                "risk": "low",
                "evidence_quote": "",
                "evidence_location": "",
                "reason": "作者对实验外推范围的保守判断。",
            },
        ],
        review=review,
    )
    unsafe_audit = ClaimAudit(
        publishable=False,
        summary="结论仍然超过论文测试范围。",
        claims=[
            {
                "claim": "不能直接推成所有自动化任务都更便宜",
                "kind": "causal",
                "support_status": "unsupported",
                "risk": "high",
                "evidence_quote": "",
                "evidence_location": "",
                "reason": "第一次审计要求把普遍结论改成范围限制。",
            }
        ],
        review=review,
    )

    class FakeProvider:
        name = "fake"
        model = "fake-model"
        audit_calls = 0

        async def complete(
            self,
            system_prompt: str,
            user_prompt: str,
            *,
            json_schema: dict[str, object] | None = None,
        ) -> WritingResponse:
            del system_prompt, user_prompt
            if json_schema is None:
                output = draft
            elif json_schema.get("title") == "VerifiedWriting":
                output = verified.model_dump_json()
            else:
                self.audit_calls += 1
                output = (
                    unsafe_audit.model_dump_json()
                    if self.audit_calls == 1
                    else audit.model_dump_json()
                )
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
        claim_ledger=[],
        verification={},
        final_content=None,
        status="angles_ready",
        provider=None,
        model=None,
        prompt_version=None,
        error_summary=None,
    )
    source_pack = {
        "analysis_depth": "deep",
        "source_quality": "source_excerpt",
        "source_excerpt": (
            "Only 1.1% of main-agent steps use the GUI subagent. "
            "The agent reads files and DOM structures directly."
        ),
    }
    service = WritingService(WritingConfig(), provider=FakeProvider())
    monkeypatch.setattr(service, "get", lambda session, project_id: project)
    monkeypatch.setattr(
        service,
        "_source_pack",
        lambda session, article_id: source_pack,
    )

    result = asyncio.run(
        service.generate_draft(
            FakeSession(),  # type: ignore[arg-type]
            uuid4(),
            angle_id="technical",
            output_format="short_post",
            human_input=HumanInput(),
        )
    )

    assert result.draft_content == draft
    assert result.final_content == final
    assert result.status == "verified_ready"
    assert result.verification["publishable"] is True
    assert len(result.claim_ledger) == 3
    assert result.error_summary is None
    assert service.provider.audit_calls == 2


def test_claim_audit_rejects_new_version_or_untraceable_quote() -> None:
    content = "项目方的测试显示 GPT-5.6 得分 54.8。"
    source_pack = {"source_excerpt": "GPT-5.4 scored 54.8 in the project table."}
    audit = ClaimAudit(
        publishable=True,
        summary="看似可以发布。",
        claims=[
            {
                "claim": "GPT-5.6 得分 54.8",
                "kind": "version",
                "support_status": "supported",
                "risk": "high",
                "evidence_quote": "GPT-5.6 scored 54.8",
                "evidence_location": "source_excerpt",
                "reason": "声称来自表格。",
            }
        ],
        review=_publishable_review(),
    )

    try:
        _validate_claim_audit(audit, source_pack, content)
    except ValueError as exc:
        assert "缺少可追溯" in str(exc)
    else:
        raise AssertionError("a model version absent from evidence must be rejected")


def test_claim_audit_rejects_numbers_omitted_from_ledger() -> None:
    content = "模型共有 93 层，其中注意力结构经过调整。"
    source_pack = {"source_excerpt": "The model has 93 layers."}
    audit = ClaimAudit(
        publishable=True,
        summary="机制描述有证据。",
        claims=[
            {
                "claim": "注意力结构经过调整",
                "kind": "fact",
                "support_status": "supported",
                "risk": "medium",
                "evidence_quote": "The model has 93 layers.",
                "evidence_location": "source_excerpt",
                "reason": "引用了原始资料。",
            }
        ],
        review=_publishable_review(),
    )

    try:
        _validate_claim_audit(audit, source_pack, content)
    except ValueError as exc:
        assert "没有进入主张账本" in str(exc)
    else:
        raise AssertionError("every material number must appear in a metric claim")


def _publishable_review() -> WritingReview:
    return WritingReview(
        verdict="事实边界清楚，可以继续编辑或发布。",
        thesis_clarity=9,
        originality=8,
        technical_clarity=9,
        accessibility=9,
        human_voice=8,
        issues=[],
        strongest_line="事实边界清楚。",
        cut_suggestions=[],
    )


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


def test_angle_allows_a_technical_term_that_can_be_explained_in_prose() -> None:
    angle_set = WritingAngleSet(
        angles=[
            _angle(
                label="少看屏幕",
                thesis=(
                    "长程任务不必每一步都看截图；StateAct 只在 1.1% 的步骤里"
                    "调用视觉操作，其余步骤直接读取程序状态。"
                ),
            )
        ]
    )

    _validate_angle_set(
        angle_set,
        {
            "title": "StateAct",
            "source_excerpt": "Only 1.1% of main-agent steps use the GUI subagent.",
        },
    )


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
