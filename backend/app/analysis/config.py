from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANALYSIS_CONFIG_PATH = BACKEND_ROOT / "config" / "analysis.json"


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: Literal["deterministic", "openai", "bailian"] = "deterministic"
    model: str = "deterministic-v1"
    api_base: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    prompt_path: Path = Path("config/prompts/article-analysis-v1.txt")
    brief_prompt_path: Path = Path("config/prompts/article-brief-v1.txt")
    prompt_version: str = "article-analysis-v1"
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=1, ge=0, le=60)
    timeout_seconds: float = Field(default=60, ge=1, le=300)
    max_input_characters: int = Field(default=12_000, ge=500, le=100_000)
    max_output_tokens: int = Field(default=2_000, ge=500, le=16_000)

    @classmethod
    def from_file(cls, path: Path = DEFAULT_ANALYSIS_CONFIG_PATH) -> "AnalysisConfig":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def load_system_prompt(self, depth: Literal["brief", "deep"] = "deep") -> str:
        path = self.brief_prompt_path if depth == "brief" else self.prompt_path
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.read_text(encoding="utf-8").strip()
