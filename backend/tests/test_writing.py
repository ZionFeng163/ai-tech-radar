import asyncio
import json

import httpx

from app.writing.config import DEFAULT_WRITING_CONFIG_PATH, WritingConfig
from app.writing.provider import BailianWritingProvider
from app.writing.schema import WritingAngleSet
from app.writing.service import _validate_draft_format


def test_writing_config_uses_separate_qwen_pipeline() -> None:
    config = WritingConfig.from_file(DEFAULT_WRITING_CONFIG_PATH)

    assert config.provider == "bailian"
    assert config.model == "qwen3.7-plus-2026-05-26"
    assert config.prompt_version == "writing-studio-v1"
    assert config.max_output_tokens > 2_000


def test_writing_provider_only_enables_json_mode_for_structured_stages(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "draft"}}]},
        )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BailianWritingProvider(WritingConfig(), client=client)

    asyncio.run(provider.complete("system", "user"))
    asyncio.run(provider.complete("system", "user", json_schema={"type": "object"}))
    asyncio.run(client.aclose())

    assert "response_format" not in captured[0]
    assert captured[1]["response_format"] == {"type": "json_object"}
    assert captured[0]["enable_thinking"] is False


def test_thread_format_rejects_oversized_or_wrong_post_count() -> None:
    valid = "\n\n".join(f"{index}/4 " + "观点" * 20 for index in range(1, 5))
    _validate_draft_format(valid, "thread")

    too_long = "\n\n".join(["1/4 " + "长" * 281, "2/4 ok", "3/4 ok", "4/4 ok"])
    try:
        _validate_draft_format(too_long, "thread")
    except ValueError as exc:
        assert "超过 280" in str(exc)
    else:
        raise AssertionError("oversized posts must be rejected")

    try:
        _validate_draft_format("1/2 one\n\n2/2 two", "thread")
    except ValueError as exc:
        assert "4–6" in str(exc)
    else:
        raise AssertionError("short threads must be rejected")


def test_angle_schema_requires_three_distinct_editorial_slots() -> None:
    schema = WritingAngleSet.model_json_schema()

    assert schema["properties"]["angles"]["minItems"] == 3
    assert schema["properties"]["angles"]["maxItems"] == 3
