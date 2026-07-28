from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WritingFormat = Literal["short_post", "thread", "article"]


class HumanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core_take: str = Field(default="", max_length=2_000)
    personal_observation: str = Field(default="", max_length=2_000)
    disagreement: str = Field(default="", max_length=2_000)


class WritingAngle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["technical", "industry", "practitioner"]
    label: str = Field(min_length=2, max_length=40)
    thesis: str = Field(min_length=10, max_length=300)
    signal: str = Field(min_length=10, max_length=500)
    mechanism: str = Field(default="", max_length=800)
    change: str = Field(default="", max_length=800)
    tension: str = Field(default="", max_length=800)
    evidence: list[str] = Field(min_length=1, max_length=5)
    counterargument: str = Field(default="", max_length=600)
    uncertainty: str = Field(default="", max_length=500)
    reader_gain: str = Field(min_length=10, max_length=400)
    recommended_format: WritingFormat
    value_score: float = Field(ge=0, le=10)


class WritingAngleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angles: list[WritingAngle] = Field(min_length=1, max_length=3)


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "fact", "generic", "ai_tone", "logic", "voice", "jargon", "format"
    ]
    severity: Literal["high", "medium", "low"]
    quote: str = Field(max_length=500)
    problem: str = Field(min_length=2, max_length=500)
    suggestion: str = Field(min_length=2, max_length=800)


class WritingReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(min_length=5, max_length=500)
    thesis_clarity: float = Field(ge=0, le=10)
    originality: float = Field(ge=0, le=10)
    technical_clarity: float = Field(ge=0, le=10)
    accessibility: float = Field(default=0, ge=0, le=10)
    human_voice: float = Field(ge=0, le=10)
    issues: list[ReviewIssue] = Field(max_length=12)
    strongest_line: str = Field(max_length=500)
    cut_suggestions: list[str] = Field(max_length=8)


class WritingClaim(BaseModel):
    """One exact claim span from a draft and the evidence decision for it."""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=800)
    kind: Literal["fact", "metric", "version", "causal", "inference", "opinion"]
    support_status: Literal["supported", "inference", "unsupported", "contradicted"]
    risk: Literal["high", "medium", "low"]
    evidence_quote: str = Field(default="", max_length=2_000)
    evidence_location: str = Field(default="", max_length=300)
    reason: str = Field(min_length=2, max_length=800)


class ClaimAudit(BaseModel):
    """A bounded, machine-checkable audit of the content that will be published."""

    model_config = ConfigDict(extra="forbid")

    publishable: bool
    summary: str = Field(min_length=2, max_length=800)
    claims: list[WritingClaim] = Field(min_length=1, max_length=30)
    review: WritingReview


class VerifiedWriting(BaseModel):
    """The correction-only output before an independent final claim audit."""

    model_config = ConfigDict(extra="forbid")

    final_content: str = Field(min_length=1, max_length=30_000)
    changes: list[str] = Field(max_length=12)


def strict_schema(model: type[BaseModel]) -> dict[str, object]:
    return model.model_json_schema()
