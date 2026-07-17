import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import quote, urlparse

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.domain import ArticleKind, SourceKind
from app.sources.base import (
    AdapterCursor,
    AuthorData,
    CollectedItem,
    FetchBatch,
    NormalizedItem,
    SourceAdapter,
    SourceDescriptor,
)
from app.sources.hugging_face.config import (
    HuggingFaceConfig,
    HuggingFaceResourceType,
)

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]
JSON_OBJECTS = TypeAdapter(list[dict[str, JsonValue]])
RATE_LIMIT_RESET_PATTERN = re.compile(r"(?:^|[;,])\s*t=(?P<seconds>\d+(?:\.\d+)?)")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class HuggingFaceRateLimitError(RuntimeError):
    pass


class _HubQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_type: HuggingFaceResourceType
    filter: str | None = None
    author: str | None = None

    @property
    def key(self) -> str:
        return f"{self.resource_type.value}|{self.filter or '*'}|{self.author or '*'}"


class _HubCursor(BaseModel):
    queries: list[_HubQuery] = Field(default_factory=list)
    query_index: int = Field(default=0, ge=0)
    next_url: str | None = None
    watermarks: dict[str, str] = Field(default_factory=dict)
    query_max_modified: str | None = None
    errors: list[dict[str, str]] = Field(default_factory=list)
    completed: bool = False

    def adapter_cursor(self) -> AdapterCursor:
        return AdapterCursor(value=self.model_dump(mode="json"))


class HuggingFaceAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        slug="hugging-face",
        name="Hugging Face Hub",
        kind=SourceKind.HUGGING_FACE,
        base_url=AnyHttpUrl("https://huggingface.co"),
    )

    def __init__(
        self,
        config: HuggingFaceConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Clock = _utc_now,
        monotonic: MonotonicClock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self.config = config or HuggingFaceConfig()
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        headers = {"User-Agent": self.config.user_agent, "Accept": "application/json"}
        if self.config.token is not None:
            headers["Authorization"] = f"Bearer {self.config.token.get_secret_value()}"
        self._default_headers = headers
        self._client = client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers=headers,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._last_request_at: float | None = None

    async def __aenter__(self) -> "HuggingFaceAdapter":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        state = self._prepare_cursor(cursor)

        while state.query_index < len(state.queries):
            query = state.queries[state.query_index]
            first_page = state.next_url is None
            url = state.next_url or self._query_url(query)
            try:
                response = await self._request(
                    url,
                    params=self._query_params(query, min(limit, self.config.page_size))
                    if first_page
                    else None,
                )
                values = JSON_OBJECTS.validate_python(response.json())
                next_url = self._next_link(response.headers.get("link"))
            except HuggingFaceRateLimitError:
                raise
            except (httpx.HTTPError, ValueError) as error:
                self._record_error(state, query, error, operation="query")
                self._complete_query(state)
                continue

            cutoff = self._query_cutoff(state, query)
            items: list[CollectedItem] = []
            reached_cutoff = False
            for value in values:
                try:
                    modified_value = self._required_string(value, "lastModified")
                    modified = self._parse_datetime(modified_value)
                    if modified < cutoff:
                        reached_cutoff = True
                        break
                    item = self._collected_item(query, value)
                except (ValueError, TypeError) as error:
                    self._record_error(
                        state,
                        query,
                        error,
                        operation="item",
                        item_id=self._item_label(value),
                    )
                    continue
                self._remember_query_maximum(state, modified)
                items.append(item)

            if reached_cutoff or next_url is None:
                self._complete_query(state)
            else:
                state.next_url = next_url

            if items:
                return FetchBatch(
                    items=items,
                    next_cursor=state.adapter_cursor(),
                    has_more=not state.completed,
                )

        state.completed = True
        return FetchBatch(items=[], next_cursor=state.adapter_cursor(), has_more=False)

    def normalize(self, item: CollectedItem) -> NormalizedItem:
        payload = item.payload
        resource_value = self._required_string(payload, "_resource_type")
        resource_type = HuggingFaceResourceType(resource_value)
        repo_id = self._required_string(payload, "id")
        card_value = payload.get("cardData")
        card_data: dict[str, JsonValue] = card_value if isinstance(card_value, dict) else {}
        tags_value = payload.get("tags", [])
        tags = [value for value in cast(list[JsonValue], tags_value) if isinstance(value, str)]
        author = self._optional_string(payload, "author") or repo_id.split("/", 1)[0]
        title = self._card_title(card_data) or repo_id.rsplit("/", 1)[-1]
        description = self._optional_string(payload, "description") or self._card_description(
            card_data
        )
        last_modified = self._required_string(payload, "lastModified")
        created_at = self._optional_string(payload, "createdAt") or last_modified
        pipeline_tag = self._optional_string(payload, "pipeline_tag")
        license_name = self._license(card_data, tags)
        kind = (
            ArticleKind.MODEL
            if resource_type is HuggingFaceResourceType.MODEL
            else ArticleKind.DATASET
        )
        metadata: dict[str, JsonValue] = {
            "provider": "hugging_face",
            "resource_type": resource_type.value,
            "repo_id": repo_id,
            "author": author,
            "pipeline_tag": pipeline_tag,
            "downloads": payload.get("downloads"),
            "likes": payload.get("likes"),
            "sha": payload.get("sha"),
            "private": payload.get("private"),
            "gated": payload.get("gated"),
            "disabled": payload.get("disabled"),
            "library_name": payload.get("library_name"),
            "created_at": payload.get("createdAt"),
            "last_modified": payload.get("lastModified"),
            "tags": cast(list[JsonValue], tags),
            "card_data": card_data,
            "query": payload.get("_query"),
        }
        return NormalizedItem(
            external_id=item.external_id,
            kind=kind,
            canonical_url=item.url,
            title=title,
            content=description,
            published_at=self._parse_datetime(created_at),
            updated_at=self._parse_datetime(last_modified),
            authors=[
                AuthorData(
                    name=author,
                    url=AnyHttpUrl(f"{self.config.endpoint}{quote(author, safe='')}")
                    if author
                    else None,
                    external_ids={"hugging_face_author": author} if author else {},
                )
            ]
            if author
            else [],
            tags=tags,
            license=license_name,
            metadata=metadata,
        )

    def _prepare_cursor(self, cursor: AdapterCursor | None) -> _HubCursor:
        previous = _HubCursor.model_validate(cursor.value) if cursor else _HubCursor()
        if previous.completed or not previous.queries:
            queries = self._queries()
            initial = self._aware_now() - timedelta(hours=self.config.initial_window_hours)
            watermarks = {
                query.key: previous.watermarks.get(query.key, initial.isoformat())
                for query in queries
            }
            return _HubCursor(queries=queries, watermarks=watermarks)
        if previous.query_index > len(previous.queries):
            raise ValueError("Hugging Face cursor query index is out of range")
        return previous

    def _queries(self) -> list[_HubQuery]:
        authors = list(dict.fromkeys([*self.config.authors, *self.config.organizations]))
        author_values: list[str | None] = [*authors] if authors else [None]
        queries: list[_HubQuery] = []
        if HuggingFaceResourceType.MODEL in self.config.resource_types:
            model_filters: list[str | None] = (
                [*self.config.model_tasks] if self.config.model_tasks else [None]
            )
            queries.extend(
                _HubQuery(
                    resource_type=HuggingFaceResourceType.MODEL,
                    filter=filter_value,
                    author=author,
                )
                for author in author_values
                for filter_value in model_filters
            )
        if HuggingFaceResourceType.DATASET in self.config.resource_types:
            dataset_filters: list[str | None] = (
                [*self.config.dataset_filters] if self.config.dataset_filters else [None]
            )
            queries.extend(
                _HubQuery(
                    resource_type=HuggingFaceResourceType.DATASET,
                    filter=filter_value,
                    author=author,
                )
                for author in author_values
                for filter_value in dataset_filters
            )
        if not queries:
            raise ValueError("Hugging Face configuration did not produce any queries")
        return list({query.key: query for query in queries}.values())

    def _query_url(self, query: _HubQuery) -> str:
        collection = (
            "models" if query.resource_type is HuggingFaceResourceType.MODEL else "datasets"
        )
        return f"{self.config.endpoint}api/{collection}"

    @staticmethod
    def _query_params(query: _HubQuery, limit: int) -> dict[str, str | int | bool]:
        params: dict[str, str | int | bool] = {
            "sort": "lastModified",
            "direction": -1,
            "limit": limit,
            "full": True,
        }
        if query.resource_type is HuggingFaceResourceType.MODEL:
            params["cardData"] = True
            if query.filter:
                params["pipeline_tag"] = query.filter
        elif query.filter:
            params["filter"] = query.filter
        if query.author:
            params["author"] = query.author
        return params

    async def _request(
        self,
        url: str,
        *,
        params: dict[str, str | int | bool] | None = None,
    ) -> httpx.Response:
        for attempt in range(self.config.max_retries + 1):
            await self._respect_request_interval()
            try:
                response = await self._client.get(
                    url,
                    params=params,
                    headers=self._default_headers,
                )
            except httpx.TransportError as error:
                if attempt >= self.config.max_retries:
                    raise
                delay = self.config.retry_backoff_seconds * (2**attempt)
                logger.warning("Hugging Face transport error; retrying in %.1fs: %s", delay, error)
                await self._sleep(delay)
                continue

            if response.status_code == 429:
                delay = self._rate_limit_delay(response, attempt)
                if attempt >= self.config.max_retries:
                    raise HuggingFaceRateLimitError(
                        f"Hugging Face rate limit exhausted after {attempt + 1} attempts"
                    )
                logger.warning("Hugging Face rate limit; retrying in %.1fs", delay)
                await self._sleep(delay)
                continue
            if response.status_code >= 500:
                if attempt >= self.config.max_retries:
                    response.raise_for_status()
                delay = self.config.retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "Hugging Face server response %s; retrying in %.1fs",
                    response.status_code,
                    delay,
                )
                await self._sleep(delay)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("Hugging Face request retry loop exited unexpectedly")

    def _rate_limit_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self.config.default_rate_limit_wait_seconds * (2**attempt)
        elif match := RATE_LIMIT_RESET_PATTERN.search(response.headers.get("ratelimit", "")):
            delay = float(match.group("seconds"))
        else:
            delay = self.config.default_rate_limit_wait_seconds * (2**attempt)
        return min(delay, self.config.max_rate_limit_wait_seconds)

    async def _respect_request_interval(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self.config.request_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                await self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _collected_item(
        self,
        query: _HubQuery,
        value: dict[str, JsonValue],
    ) -> CollectedItem:
        repo_id = self._required_string(value, "id")
        payload = dict(value)
        payload["_resource_type"] = query.resource_type.value
        payload["_query"] = query.model_dump(mode="json")
        prefix = "datasets/" if query.resource_type is HuggingFaceResourceType.DATASET else ""
        url = f"{self.config.endpoint}{prefix}{quote(repo_id, safe='/')}"
        return CollectedItem(
            external_id=f"{query.resource_type.value}:{repo_id}",
            url=AnyHttpUrl(url),
            payload=payload,
            fetched_at=self._aware_now(),
        )

    def _query_cutoff(self, state: _HubCursor, query: _HubQuery) -> datetime:
        watermark = state.watermarks.get(query.key)
        if watermark is None:
            raise ValueError(f"missing watermark for Hugging Face query {query.key}")
        return self._parse_datetime(watermark) - timedelta(seconds=self.config.overlap_seconds)

    @staticmethod
    def _remember_query_maximum(state: _HubCursor, modified: datetime) -> None:
        current = (
            HuggingFaceAdapter._parse_datetime(state.query_max_modified)
            if state.query_max_modified
            else None
        )
        if current is None or modified > current:
            state.query_max_modified = modified.isoformat()

    @staticmethod
    def _complete_query(state: _HubCursor) -> None:
        if state.query_index >= len(state.queries):
            state.completed = True
            return
        query = state.queries[state.query_index]
        if state.query_max_modified:
            previous = HuggingFaceAdapter._parse_datetime(state.watermarks[query.key])
            maximum = HuggingFaceAdapter._parse_datetime(state.query_max_modified)
            state.watermarks[query.key] = max(previous, maximum).isoformat()
        state.query_index += 1
        state.next_url = None
        state.query_max_modified = None
        if state.query_index >= len(state.queries):
            state.completed = True

    def _next_link(self, value: str | None) -> str | None:
        if value is None:
            return None
        endpoint_host = urlparse(str(self.config.endpoint)).netloc
        for part in value.split(","):
            segments = [segment.strip() for segment in part.split(";")]
            if len(segments) < 2 or 'rel="next"' not in segments[1:]:
                continue
            candidate = segments[0].removeprefix("<").removesuffix(">")
            parsed = urlparse(candidate)
            if parsed.scheme != "https" or parsed.netloc != endpoint_host:
                raise ValueError("Hugging Face pagination link points outside the configured host")
            return candidate
        return None

    def _record_error(
        self,
        state: _HubCursor,
        query: _HubQuery,
        error: Exception,
        *,
        operation: str,
        item_id: str | None = None,
    ) -> None:
        message = str(error).replace("\n", " ")[:500]
        logger.warning(
            "Hugging Face %s failed for %s%s: %s",
            operation,
            query.key,
            f" item {item_id}" if item_id else "",
            message,
        )
        error_value = {"query": query.key, "operation": operation, "error": message}
        if item_id:
            error_value["item_id"] = item_id
        state.errors.append(error_value)
        state.errors = state.errors[-self.config.max_cursor_errors :]

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Hugging Face timestamp must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _required_string(payload: dict[str, JsonValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Hugging Face payload field {key!r} must be a non-empty string")
        return value

    @staticmethod
    def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _item_label(payload: dict[str, JsonValue]) -> str:
        value = payload.get("id") or payload.get("modelId") or payload.get("_id")
        return str(value)[:200] if value is not None else "unknown"

    @staticmethod
    def _card_title(card_data: Mapping[str, object]) -> str | None:
        for key in ("pretty_name", "model_name", "title"):
            value = card_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _card_description(card_data: Mapping[str, object]) -> str | None:
        value = card_data.get("description")
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _license(card_data: Mapping[str, object], tags: list[str]) -> str | None:
        value = card_data.get("license")
        if isinstance(value, str) and value:
            return value[:255]
        if isinstance(value, list):
            licenses = [item for item in value if isinstance(item, str)]
            if licenses:
                return ",".join(licenses)[:255]
        for tag in tags:
            if tag.startswith("license:"):
                return tag.removeprefix("license:")[:255]
        return None
