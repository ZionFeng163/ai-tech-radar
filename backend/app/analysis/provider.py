from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import httpx

from app.analysis.config import AnalysisConfig
from app.analysis.schema import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    ArticleAnalysisInput,
    ArticleAnalysisV1,
    ArticleBriefV1,
    OpenSourceStatus,
    TechnicalCategory,
)


@dataclass(frozen=True, slots=True)
class LLMRequest:
    system_prompt: str
    user_prompt: str
    article: ArticleAnalysisInput
    json_schema: dict[str, Any]
    depth: Literal["brief", "deep"] = "deep"

    def audit_payload(self, model: str) -> dict[str, object]:
        return {
            "model": model,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "schema_name": SCHEMA_NAME,
            "schema": self.json_schema,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class LLMResponse:
    raw_response: str
    output_text: str
    response_id: str | None = None
    usage: dict[str, object] | None = None


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        raw_response: str | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.retryable = retryable


class AnalysisProvider(Protocol):
    name: str
    model: str

    async def analyze(self, request: LLMRequest) -> LLMResponse: ...


class OpenAIResponsesProvider:
    name = "openai"

    def __init__(
        self,
        config: AnalysisConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise ValueError(f"{config.api_key_env} is required for the openai provider")
        self.model = config.model
        self._endpoint = f"{config.api_base.rstrip('/')}/responses"
        self._api_key = api_key
        self._timeout = config.timeout_seconds
        self._max_output_tokens = config.max_output_tokens
        self._client = client

    async def analyze(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": SCHEMA_NAME,
                    "strict": True,
                    "schema": request.json_schema,
                }
            },
            "max_output_tokens": self._max_output_tokens,
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        raw_response = response.text
        if response.is_error:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise ProviderError(
                f"OpenAI returned HTTP {response.status_code}",
                raw_response=raw_response,
                retryable=retryable,
            )
        try:
            data = cast(dict[str, Any], response.json())
            output_text = _response_output_text(data)
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderError(
                f"OpenAI response did not contain structured output: {exc}",
                raw_response=raw_response,
            ) from exc
        usage = data.get("usage")
        return LLMResponse(
            raw_response=raw_response,
            output_text=output_text,
            response_id=data.get("id") if isinstance(data.get("id"), str) else None,
            usage=cast(dict[str, object], usage) if isinstance(usage, dict) else None,
        )


class BailianChatProvider:
    """Alibaba Cloud Model Studio via its OpenAI-compatible Chat API."""

    name = "bailian"

    def __init__(
        self,
        config: AnalysisConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise ValueError(f"{config.api_key_env} is required for the bailian provider")
        self.model = config.model
        self._endpoint = f"{config.api_base.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._timeout = config.timeout_seconds
        self._max_output_tokens = config.max_output_tokens
        self._client = client

    async def analyze(self, request: LLMRequest) -> LLMResponse:
        schema_instruction = (
            f"\n\n输出必须是符合以下 JSON Schema 的单个 JSON 对象：\n"
            f"{json.dumps(request.json_schema, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt + schema_instruction},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "max_tokens": self._max_output_tokens,
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Bailian request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        raw_response = response.text
        if response.is_error:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise ProviderError(
                f"Bailian returned HTTP {response.status_code}",
                raw_response=raw_response,
                retryable=retryable,
            )
        try:
            data = cast(dict[str, Any], response.json())
            output_text = _chat_completion_output_text(data)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderError(
                f"Bailian response did not contain JSON output: {exc}",
                raw_response=raw_response,
            ) from exc
        usage = data.get("usage")
        return LLMResponse(
            raw_response=raw_response,
            output_text=output_text,
            response_id=data.get("id") if isinstance(data.get("id"), str) else None,
            usage=cast(dict[str, object], usage) if isinstance(usage, dict) else None,
        )


def _response_output_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    output = data.get("output")
    if not isinstance(output, list):
        raise KeyError("output")
    for message in output:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "refusal":
                raise ValueError(str(item.get("refusal", "model refused the request")))
            text = item.get("text")
            if item.get("type") == "output_text" and isinstance(text, str):
                return text
    raise KeyError("output_text")


def _chat_completion_output_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise KeyError("choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError("choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise KeyError("message")
    content = message.get("content")
    if not isinstance(content, str) or not content:
        raise KeyError("content")
    return content


class DeterministicAnalysisProvider:
    """Offline development provider that emits the same versioned contract without a key."""

    name = "deterministic"

    def __init__(self, model: str = "deterministic-v1") -> None:
        self.model = model

    async def analyze(self, request: LLMRequest) -> LLMResponse:
        article = request.article
        category = _classify(article)
        open_source = _open_source_status(article)
        tags = list(dict.fromkeys([category.value, *article.existing_tags]))[:8]
        if len(tags) == 1:
            tags.append(article.kind)
        source_phrase = "、".join(article.source_names[:2]) or "现有资料"
        summary = (
            f"《{article.title}》聚焦于{_category_name(category)}方向。"
            f"根据{source_phrase}提供的信息，该条目介绍了相关方法、产品或资源的最新进展；"
            "具体效果与适用边界仍应以原始资料和后续复现实验为准。"
        )
        if request.depth == "brief":
            brief = ArticleBriefV1(
                schema_version=SCHEMA_VERSION,
                technical_category=category,
                signal_type="technical",
                tags=tags,
                summary_zh=summary,
                technical_overview=f"资料指向{_category_name(category)}方向的技术或工程变化，具体机制仍需结合原始资料确认。",
                novelty_summary="当前资料可确认有新变化，但尚不足以判断它是否形成显著技术突破。",
                heat_reasons=["若后续效果得到复现，可能引发相关开发者讨论"],
                heat_score=_importance_score(article, category),
                open_source_status=open_source,
                credibility_score=8.0 if article.source_urls else 6.0,
                importance_score=_importance_score(article, category),
            )
            output = brief.model_dump_json()
            raw = json.dumps(
                {"provider": self.name, "model": self.model, "output_text": output},
                ensure_ascii=False,
            )
            return LLMResponse(raw_response=raw, output_text=output)
        result = ArticleAnalysisV1(
            schema_version=SCHEMA_VERSION,
            technical_category=category,
            tags=tags,
            summary_zh=summary,
            core_innovations=[f"围绕{_category_name(category)}提供新的技术或工程进展"],
            differences_from_prior_work=["现有资料未提供完整对照实验，差异需结合原文确认"],
            application_scenarios=[_application_scenario(category)],
            open_source_status=open_source,
            credibility_score=8.0 if article.source_urls else 6.0,
            importance_score=_importance_score(article, category),
            why_it_matters=(
                f"该进展可能影响{_application_scenario(category)}的实现成本、能力边界或采用路径，"
                "值得继续跟踪原始证据与社区反馈。"
            ),
        )
        output = result.model_dump_json()
        raw = json.dumps(
            {"provider": self.name, "model": self.model, "output_text": output},
            ensure_ascii=False,
        )
        return LLMResponse(raw_response=raw, output_text=output)


def create_provider(config: AnalysisConfig) -> AnalysisProvider:
    if config.provider == "bailian":
        return BailianChatProvider(config)
    if config.provider == "openai":
        return OpenAIResponsesProvider(config)
    return DeterministicAnalysisProvider(config.model)


_CATEGORY_KEYWORDS: tuple[tuple[TechnicalCategory, tuple[str, ...]], ...] = (
    (TechnicalCategory.AGENTS, ("agent", "tool use", "mcp", "智能体")),
    (TechnicalCategory.MULTIMODAL, ("multimodal", "vision-language", "vlm", "多模态")),
    (TechnicalCategory.SPEECH_AUDIO, ("speech", "audio", "tts", "asr", "语音", "音频")),
    (TechnicalCategory.ROBOTICS, ("robot", "embodied", "具身", "机器人")),
    (TechnicalCategory.SAFETY, ("safety", "alignment", "red team", "安全", "对齐")),
    (TechnicalCategory.EVALUATION, ("benchmark", "evaluation", "评测", "基准")),
    (TechnicalCategory.DATA, ("dataset", "data curation", "synthetic data", "数据集")),
    (
        TechnicalCategory.INFRASTRUCTURE,
        ("cuda", "pytorch", "distributed", "kubernetes", "基础设施", "gpu kernel"),
    ),
    (
        TechnicalCategory.INFERENCE,
        ("inference", "quantization", "serving", "vllm", "推理", "量化", "latency"),
    ),
    (
        TechnicalCategory.TRAINING,
        ("training", "fine-tuning", "finetuning", "lora", "distillation", "训练", "微调"),
    ),
    (
        TechnicalCategory.COMPUTER_VISION,
        ("segmentation", "detection", "computer vision", "image", "视觉", "图像"),
    ),
    (
        TechnicalCategory.NLP,
        ("retrieval", "rag", "embedding", "translation", "nlp", "检索", "文本"),
    ),
    (
        TechnicalCategory.FOUNDATION_MODELS,
        ("large language", "foundation model", "llm", "transformer", "diffusion", "大模型"),
    ),
)


def _classify(article: ArticleAnalysisInput) -> TechnicalCategory:
    title = article.title.casefold()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in title for keyword in keywords):
            return category
    haystack = f"{article.content}\n{' '.join(article.existing_tags)}".casefold()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return category
    if article.kind == "dataset":
        return TechnicalCategory.DATA
    return TechnicalCategory.OTHER


def _open_source_status(article: ArticleAnalysisInput) -> OpenSourceStatus:
    text = f"{article.license or ''} {article.title} {article.content}".casefold()
    if any(word in text for word in ("closed source", "proprietary", "api only", "闭源")):
        return OpenSourceStatus.CLOSED
    if any(word in text for word in ("weights only", "部分开源", "partial open")):
        return OpenSourceStatus.PARTIAL
    if article.license or any(
        word in text for word in ("open source", "open-source", "开源", "github.com")
    ):
        return OpenSourceStatus.OPEN
    return OpenSourceStatus.UNKNOWN


def _importance_score(article: ArticleAnalysisInput, category: TechnicalCategory) -> float:
    score = 5.5
    if article.kind in {"paper", "model", "release"}:
        score += 0.8
    if category is not TechnicalCategory.OTHER:
        score += 0.7
    if len(article.content) >= 500:
        score += 0.5
    return min(score, 10)


def _category_name(category: TechnicalCategory) -> str:
    names = {
        TechnicalCategory.FOUNDATION_MODELS: "基础模型",
        TechnicalCategory.TRAINING: "训练与微调",
        TechnicalCategory.INFERENCE: "推理与部署",
        TechnicalCategory.AGENTS: "智能体",
        TechnicalCategory.MULTIMODAL: "多模态",
        TechnicalCategory.COMPUTER_VISION: "计算机视觉",
        TechnicalCategory.NLP: "自然语言处理",
        TechnicalCategory.SPEECH_AUDIO: "语音与音频",
        TechnicalCategory.ROBOTICS: "机器人与具身智能",
        TechnicalCategory.DATA: "数据工程",
        TechnicalCategory.EVALUATION: "评测",
        TechnicalCategory.INFRASTRUCTURE: "AI 基础设施",
        TechnicalCategory.SAFETY: "安全与对齐",
        TechnicalCategory.OTHER: "AI 技术",
    }
    return names[category]


def _application_scenario(category: TechnicalCategory) -> str:
    scenarios = {
        TechnicalCategory.FOUNDATION_MODELS: "通用 AI 助手与行业模型",
        TechnicalCategory.TRAINING: "模型训练、微调与能力适配",
        TechnicalCategory.INFERENCE: "低成本在线推理与边缘部署",
        TechnicalCategory.AGENTS: "自动化工作流与工具调用",
        TechnicalCategory.MULTIMODAL: "跨模态内容理解与生成",
        TechnicalCategory.COMPUTER_VISION: "视觉识别、检测与内容生产",
        TechnicalCategory.NLP: "知识检索、文本理解与生成",
        TechnicalCategory.SPEECH_AUDIO: "语音交互、转写与音频生成",
        TechnicalCategory.ROBOTICS: "机器人控制与现实环境交互",
        TechnicalCategory.DATA: "训练数据构建与数据治理",
        TechnicalCategory.EVALUATION: "模型选型、回归测试与能力评估",
        TechnicalCategory.INFRASTRUCTURE: "训练和推理平台工程",
        TechnicalCategory.SAFETY: "模型风险治理与安全上线",
        TechnicalCategory.OTHER: "AI 产品研发与技术决策",
    }
    return scenarios[category]
