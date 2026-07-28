from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr


class HuggingFacePapersConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    endpoint: HttpUrl = HttpUrl("https://huggingface.co")
    token: SecretStr | None = None
    initial_window_hours: int = Field(default=72, ge=1, le=24 * 30)
    overlap_seconds: int = Field(default=300, ge=0, le=86_400)
    page_size: int = Field(default=30, ge=1, le=100)
    timeout_seconds: float = Field(default=15, gt=0, le=60)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=1, ge=0, le=30)
    user_agent: str = Field(
        default="ai-tech-radar/0.1 (+https://github.com/ZionFeng163/ai-tech-radar)",
        min_length=1,
        max_length=255,
    )

    @classmethod
    def from_file(cls, path: Path) -> "HuggingFacePapersConfig":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def persisted_config(self) -> dict[str, object]:
        values = self.model_dump(mode="json", exclude={"token"})
        values["authentication"] = "token" if self.token else "anonymous"
        return values
