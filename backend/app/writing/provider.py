from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx

from app.analysis.provider import ProviderError
from app.writing.config import WritingConfig


@dataclass(frozen=True, slots=True)
class WritingResponse:
    output_text: str
    raw_response: str
    usage: dict[str, object] | None = None


class WritingProvider(Protocol):
    name: str
    model: str

    async def complete(
        self, system_prompt: str, user_prompt: str, *, json_schema: dict[str, object] | None = None
    ) -> WritingResponse: ...


class BailianWritingProvider:
    name = "bailian"

    def __init__(
        self, config: WritingConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise ValueError(f"{config.api_key_env} is required for writing")
        self.model = config.model
        self._api_key = api_key
        self._endpoint = f"{config.api_base.rstrip('/')}/chat/completions"
        self._timeout = config.timeout_seconds
        self._max_output_tokens = config.max_output_tokens
        self._client = client

    async def complete(
        self, system_prompt: str, user_prompt: str, *, json_schema: dict[str, object] | None = None
    ) -> WritingResponse:
        if json_schema is not None:
            user_prompt += (
                "\n\n只输出符合以下 JSON Schema 的单个 JSON 对象，"
                "不要 Markdown 代码围栏：\n"
                + json.dumps(json_schema, ensure_ascii=False)
            )
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "enable_thinking": False,
            "max_tokens": self._max_output_tokens,
        }
        if json_schema is not None:
            payload["response_format"] = {"type": "json_object"}

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Bailian writing request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        raw = response.text
        if response.is_error:
            raise ProviderError(
                f"Bailian returned HTTP {response.status_code}",
                raw_response=raw,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            data = cast(dict[str, Any], response.json())
            choices = data["choices"]
            output = choices[0]["message"]["content"]
            if not isinstance(output, str) or not output.strip():
                raise TypeError("empty content")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"Bailian writing response did not contain content: {exc}", raw_response=raw
            ) from exc
        usage = data.get("usage")
        return WritingResponse(
            output_text=output.strip(),
            raw_response=raw,
            usage=cast(dict[str, object], usage) if isinstance(usage, dict) else None,
        )
