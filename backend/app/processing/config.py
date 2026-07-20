from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PROCESSING_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "processing.json"


class ProcessingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    embedding_dimensions: int = Field(default=256, ge=64, le=4_096)
    similarity_threshold: float = Field(default=0.60, ge=0, le=1)
    event_window_hours: int = Field(default=24 * 7, ge=1, le=24 * 90)
    candidate_limit: int = Field(default=250, ge=1, le=5_000)
    content_characters: int = Field(default=0, ge=0, le=10_000)

    @classmethod
    def from_file(cls, path: Path = DEFAULT_PROCESSING_CONFIG_PATH) -> "ProcessingConfig":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
