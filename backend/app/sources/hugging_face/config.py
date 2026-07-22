import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator

FILTER_PATTERN = re.compile(r"^[A-Za-z0-9_.:/-]+$")
DEFAULT_MODEL_TASKS = [
    "text-generation",
    "image-text-to-text",
    "automatic-speech-recognition",
]


class HuggingFaceResourceType(StrEnum):
    MODEL = "model"
    DATASET = "dataset"


class HuggingFaceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    endpoint: HttpUrl = HttpUrl("https://huggingface.co")
    token: SecretStr | None = None
    resource_types: list[HuggingFaceResourceType] = Field(
        default_factory=lambda: [
            HuggingFaceResourceType.MODEL,
            HuggingFaceResourceType.DATASET,
        ]
    )
    model_tasks: list[str] = Field(default_factory=lambda: list(DEFAULT_MODEL_TASKS))
    dataset_filters: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    initial_window_hours: int = Field(default=24 * 7, ge=1, le=24 * 90)
    overlap_seconds: int = Field(default=300, ge=0, le=86_400)
    page_size: int = Field(default=30, ge=1, le=100)
    fetch_readme: bool = False
    max_readme_characters: int = Field(default=12_000, ge=500, le=50_000)
    request_interval_seconds: float = Field(default=0.2, ge=0, le=60)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=1, ge=0, le=60)
    default_rate_limit_wait_seconds: float = Field(default=60, ge=0, le=600)
    max_rate_limit_wait_seconds: float = Field(default=3_600, ge=0, le=86_400)
    max_cursor_errors: int = Field(default=50, ge=1, le=500)
    user_agent: str = Field(
        default="ai-tech-radar/0.1 (+https://github.com/ZionFeng163/ai-tech-radar)",
        min_length=1,
        max_length=255,
    )

    @field_validator("resource_types")
    @classmethod
    def deduplicate_resource_types(
        cls, values: list[HuggingFaceResourceType]
    ) -> list[HuggingFaceResourceType]:
        return list(dict.fromkeys(values))

    @field_validator("model_tasks", "dataset_filters", "authors", "organizations")
    @classmethod
    def validate_filters(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        invalid = [value for value in cleaned if FILTER_PATTERN.fullmatch(value) is None]
        if invalid:
            raise ValueError(f"invalid Hugging Face filters: {', '.join(invalid)}")
        return cleaned

    @classmethod
    def from_file(cls, path: Path) -> "HuggingFaceConfig":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def persisted_config(self) -> dict[str, object]:
        values = self.model_dump(mode="json", exclude={"token"})
        values["authentication"] = "token" if self.token else "anonymous"
        return values
