from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WRITING_CONFIG_PATH = BACKEND_ROOT / "config" / "writing.json"


class WritingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "bailian"
    model: str = "qwen3.7-flash-2026-07-15"
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_env: str = "DASHSCOPE_API_KEY"
    prompt_version: str = "writing-studio-v1"
    angle_prompt_path: Path = Path("config/prompts/writing-angles-v1.txt")
    draft_prompt_path: Path = Path("config/prompts/writing-draft-v1.txt")
    review_prompt_path: Path = Path("config/prompts/writing-review-v1.txt")
    idea_prompt_path: Path = Path("config/prompts/composer-idea-v1.txt")
    paper_prompt_path: Path = Path("config/prompts/composer-paper-v1.txt")
    github_prompt_path: Path = Path("config/prompts/composer-github-v1.txt")
    skill_path: Path = Path("config/skills/tech-social-writer/SKILL.md")
    voice_profile_path: Path = Path(
        "config/skills/tech-social-writer/references/voice-profile.md"
    )
    fact_check_path: Path = Path(
        "config/skills/tech-social-writer/references/fact-check.md"
    )
    chinese_edit_path: Path = Path(
        "config/skills/tech-social-writer/references/chinese-edit.md"
    )
    timeout_seconds: float = Field(default=120, ge=1, le=300)
    max_input_characters: int = Field(default=16_000, ge=1_000, le=100_000)
    max_output_tokens: int = Field(default=5_000, ge=500, le=16_000)

    @classmethod
    def from_file(cls, path: Path = DEFAULT_WRITING_CONFIG_PATH) -> "WritingConfig":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def load_prompt(self, stage: str) -> str:
        paths = {
            "angles": self.angle_prompt_path,
            "draft": self.draft_prompt_path,
            "review": self.review_prompt_path,
            "idea": self.idea_prompt_path,
            "paper": self.paper_prompt_path,
            "github": self.github_prompt_path,
        }
        path = paths[stage]
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.read_text(encoding="utf-8").strip()

    def load_skill(self, stage: str) -> str:
        paths = [self.skill_path]
        if stage in {"angles", "draft", "composer", "review"}:
            paths.append(self.voice_profile_path)
        if stage in {"draft", "composer", "review"}:
            paths.append(self.chinese_edit_path)
        if stage == "review":
            paths.append(self.fact_check_path)
        if stage not in {"angles", "draft", "composer", "review"}:
            raise ValueError(f"unsupported writing skill stage: {stage}")

        sections: list[str] = []
        for configured_path in paths:
            path = configured_path
            if not path.is_absolute():
                path = BACKEND_ROOT / path
            sections.append(path.read_text(encoding="utf-8").strip())
        return "\n\n".join(sections)
