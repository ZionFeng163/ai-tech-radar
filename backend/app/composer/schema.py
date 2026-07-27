from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IdeaComposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragments: str = Field(min_length=5, max_length=6_000)

    @field_validator("fragments")
    @classmethod
    def clean_fragments(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("想法至少需要 5 个字符")
        return value


class PaperComposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=500)
    emphasis: str = Field(default="", max_length=1_000)

    @field_validator("url", "emphasis")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()


class PaperSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    arxiv_id: str
    title: str
    authors: list[str]
    canonical_url: str


class ComposerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Literal["idea", "paper"]
    draft: str
    model: str
    source: PaperSource | None = None
