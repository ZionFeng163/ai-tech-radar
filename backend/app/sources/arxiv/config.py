from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class ArxivConfig(BaseModel):
    """Runtime settings for one arXiv source."""

    model_config = ConfigDict(frozen=True)

    api_url: HttpUrl = HttpUrl("https://export.arxiv.org/api/query")
    categories: list[str] = Field(
        default_factory=lambda: ["cs.AI", "cs.LG", "cs.CV", "cs.CL"],
        max_length=50,
    )
    keywords: list[str] = Field(default_factory=list, max_length=100)
    window_hours: int = Field(default=24, ge=1, le=24 * 31)
    overlap_minutes: int = Field(default=15, ge=0, le=24 * 60)
    page_size: int = Field(default=100, ge=1, le=2_000)
    request_interval_seconds: float = Field(default=3.0, ge=0, le=60)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=1.0, ge=0, le=60)
    user_agent: str = Field(
        default="ai-tech-radar/0.1 (+https://github.com/ZionFeng163/ai-tech-radar)",
        min_length=1,
        max_length=255,
    )

    @field_validator("categories", "keywords")
    @classmethod
    def clean_terms(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if len(cleaned) != len(values):
            return cleaned
        return values

    @model_validator(mode="after")
    def require_filter(self) -> "ArxivConfig":
        if not self.categories and not self.keywords:
            raise ValueError("at least one category or keyword is required")
        return self
