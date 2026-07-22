from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"
SCHEMA_NAME = "article_analysis_v1"
BRIEF_SCHEMA_NAME = "article_brief_v1"


class TechnicalCategory(StrEnum):
    FOUNDATION_MODELS = "foundation_models"
    TRAINING = "training"
    INFERENCE = "inference"
    AGENTS = "agents"
    MULTIMODAL = "multimodal"
    COMPUTER_VISION = "computer_vision"
    NLP = "nlp"
    SPEECH_AUDIO = "speech_audio"
    ROBOTICS = "robotics"
    DATA = "data"
    EVALUATION = "evaluation"
    INFRASTRUCTURE = "infrastructure"
    SAFETY = "safety"
    OTHER = "other"


class OpenSourceStatus(StrEnum):
    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class SignalType(StrEnum):
    TECHNICAL = "technical"
    PRODUCT = "product"
    ECOSYSTEM = "ecosystem"
    INDUSTRY = "industry"
    COMMUNITY = "community"


class ArticleAnalysisInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    kind: str
    content: str = ""
    license: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    source_names: list[str] = Field(default_factory=list)
    existing_tags: list[str] = Field(default_factory=list)
    source_context: list[dict[str, Any]] = Field(default_factory=list)


class ArticleAnalysisV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    technical_category: TechnicalCategory
    tags: list[str] = Field(min_length=1, max_length=10)
    summary_zh: str = Field(min_length=20, max_length=800)
    core_innovations: list[str] = Field(min_length=1, max_length=5)
    differences_from_prior_work: list[str] = Field(min_length=1, max_length=5)
    application_scenarios: list[str] = Field(min_length=1, max_length=5)
    open_source_status: OpenSourceStatus
    credibility_score: float = Field(ge=0, le=10)
    importance_score: float = Field(ge=0, le=10)
    why_it_matters: str = Field(min_length=10, max_length=500)

    @field_validator(
        "tags",
        "core_innovations",
        "differences_from_prior_work",
        "application_scenarios",
    )
    @classmethod
    def normalize_string_lists(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not normalized:
            raise ValueError("at least one non-empty value is required")
        return normalized

    @field_validator("summary_zh", "why_it_matters")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ArticleBriefV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    technical_category: TechnicalCategory
    signal_type: SignalType
    tags: list[str] = Field(min_length=1, max_length=8)
    summary_zh: str = Field(min_length=40, max_length=300)
    technical_overview: str = Field(min_length=20, max_length=500)
    novelty_summary: str = Field(min_length=10, max_length=300)
    heat_reasons: list[str] = Field(min_length=1, max_length=4)
    heat_score: float = Field(ge=0, le=10)
    open_source_status: OpenSourceStatus
    credibility_score: float = Field(ge=0, le=10)
    importance_score: float = Field(ge=0, le=10)

    @field_validator("tags", "heat_reasons")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not normalized:
            raise ValueError("at least one non-empty value is required")
        return normalized

    @field_validator("summary_zh", "technical_overview", "novelty_summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        return value.strip()


def strict_json_schema() -> dict[str, Any]:
    """Return the versioned schema with strict object rules at every nesting level."""

    schema = ArticleAnalysisV1.model_json_schema()
    schema["title"] = "AI Tech Radar Article Analysis v1"
    _forbid_additional_properties(schema)
    return schema


def brief_json_schema() -> dict[str, Any]:
    schema = ArticleBriefV1.model_json_schema()
    schema["title"] = "AI Tech Radar Article Brief v1"
    _forbid_additional_properties(schema)
    return schema


def _forbid_additional_properties(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            value["additionalProperties"] = False
        for child in value.values():
            _forbid_additional_properties(child)
    elif isinstance(value, list):
        for child in value:
            _forbid_additional_properties(child)
