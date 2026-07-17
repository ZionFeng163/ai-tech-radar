import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlparse

import httpx
from pydantic import AnyHttpUrl, BaseModel, Field, JsonValue, TypeAdapter

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
from app.sources.github_releases.config import GitHubReleasesConfig

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
EpochClock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
JSON_OBJECTS = TypeAdapter(list[dict[str, JsonValue]])


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GitHubRateLimitError(RuntimeError):
    pass


class _GitHubCursor(BaseModel):
    repositories: list[str] = Field(default_factory=list)
    repository_index: int = Field(default=0, ge=0)
    next_url: str | None = None
    etags: dict[str, str] = Field(default_factory=dict)
    errors: list[dict[str, str]] = Field(default_factory=list)
    completed: bool = False

    def adapter_cursor(self) -> AdapterCursor:
        return AdapterCursor(value=self.model_dump(mode="json"))


class GitHubReleasesAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        slug="github-releases",
        name="GitHub Releases",
        kind=SourceKind.GITHUB_RELEASES,
        base_url=AnyHttpUrl("https://github.com"),
    )

    def __init__(
        self,
        config: GitHubReleasesConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Clock = _utc_now,
        epoch_clock: EpochClock = time.time,
        monotonic: EpochClock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self.config = config or GitHubReleasesConfig()
        self._clock = clock
        self._epoch_clock = epoch_clock
        self._monotonic = monotonic
        self._sleep = sleep
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.config.api_version,
            "User-Agent": self.config.user_agent,
        }
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
        self._repository_metadata: dict[str, dict[str, JsonValue]] = {}

    async def __aenter__(self) -> "GitHubReleasesAdapter":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def discover_repositories(self) -> list[str]:
        repositories = list(self.config.repositories)
        seen = {value.casefold() for value in repositories}

        for organization in self.config.organizations:
            remaining = self.config.max_discovered_repositories - len(repositories)
            if remaining <= 0:
                break
            try:
                response = await self._request(
                    f"{self.config.api_url}orgs/{organization}/repos",
                    params={"sort": "updated", "direction": "desc", "per_page": remaining},
                )
                values = JSON_OBJECTS.validate_python(response.json())
            except GitHubRateLimitError:
                raise
            except (httpx.HTTPError, ValueError) as error:
                logger.warning(
                    "GitHub organization discovery failed for %s: %s", organization, error
                )
                continue
            self._append_repositories(repositories, seen, values)

        for topic in self.config.topics:
            remaining = self.config.max_discovered_repositories - len(repositories)
            if remaining <= 0:
                break
            try:
                response = await self._request(
                    f"{self.config.api_url}search/repositories",
                    params={
                        "q": f"topic:{topic}",
                        "sort": "updated",
                        "order": "desc",
                        "per_page": remaining,
                    },
                )
                result = JSON_OBJECT.validate_python(response.json())
                values = JSON_OBJECTS.validate_python(result.get("items", []))
            except GitHubRateLimitError:
                raise
            except (httpx.HTTPError, ValueError) as error:
                logger.warning("GitHub topic discovery failed for %s: %s", topic, error)
                continue
            self._append_repositories(repositories, seen, values)

        if not repositories:
            raise ValueError("GitHub configuration did not resolve any repositories")
        return repositories[: self.config.max_discovered_repositories]

    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        state = await self._prepare_cursor(cursor)

        while state.repository_index < len(state.repositories):
            repository = state.repositories[state.repository_index]
            first_page = state.next_url is None
            url = state.next_url or f"{self.config.api_url}repos/{repository}/releases"
            headers: dict[str, str] = {}
            if first_page and (etag := state.etags.get(repository)):
                headers["If-None-Match"] = etag

            try:
                response = await self._request(
                    url,
                    params=(
                        {"per_page": min(limit, self.config.page_size)} if first_page else None
                    ),
                    headers=headers,
                    allow_not_modified=first_page,
                )
            except GitHubRateLimitError:
                raise
            except (httpx.HTTPError, ValueError) as error:
                self._record_error(state, repository, error)
                self._advance_repository(state)
                continue

            if response.status_code == 304:
                self._advance_repository(state)
                continue
            if first_page and (etag := response.headers.get("etag")):
                state.etags[repository] = etag

            try:
                releases = JSON_OBJECTS.validate_python(response.json())
            except ValueError as error:
                self._record_error(state, repository, error)
                self._advance_repository(state)
                continue

            next_url = self._next_link(response.headers.get("link"))
            included_releases = [release for release in releases if self._include_release(release)]
            metadata = await self._repository_data(repository, state) if included_releases else {}
            items = [
                self._collected_item(repository, release, metadata) for release in included_releases
            ]

            if next_url is not None:
                state.next_url = next_url
            else:
                self._advance_repository(state)
            if state.repository_index >= len(state.repositories):
                state.completed = True

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
        author_value = payload.get("author")
        authors: list[AuthorData] = []
        if isinstance(author_value, dict) and isinstance(author_value.get("login"), str):
            author_id = author_value.get("id")
            author_url = author_value.get("html_url")
            authors.append(
                AuthorData(
                    name=cast(str, author_value["login"]),
                    url=AnyHttpUrl(author_url) if isinstance(author_url, str) else None,
                    external_ids={"github_user_id": str(author_id)}
                    if author_id is not None
                    else {},
                )
            )

        repository = self._required_object(payload, "repository")
        topics_value = repository.get("topics", [])
        topics = [value for value in cast(list[JsonValue], topics_value) if isinstance(value, str)]
        tag_name = self._optional_string(payload, "tag_name")
        published = self._optional_string(payload, "published_at") or self._required_string(
            payload, "created_at"
        )
        updated = self._optional_string(payload, "updated_at")
        license_value = repository.get("license")
        license_name = None
        if isinstance(license_value, dict):
            spdx_id = license_value.get("spdx_id")
            name = license_value.get("name")
            license_name = (
                spdx_id if isinstance(spdx_id, str) and spdx_id != "NOASSERTION" else name
            )

        metadata: dict[str, JsonValue] = {
            "provider": "github",
            "release_id": payload.get("id"),
            "node_id": payload.get("node_id"),
            "tag_name": tag_name,
            "target_commitish": payload.get("target_commitish"),
            "draft": payload.get("draft"),
            "prerelease": payload.get("prerelease"),
            "created_at": payload.get("created_at"),
            "published_at": payload.get("published_at"),
            "updated_at": payload.get("updated_at"),
            "repository": repository,
            "assets": payload.get("assets", []),
        }
        tags = [*topics]
        if tag_name:
            tags.append(tag_name)
        return NormalizedItem(
            external_id=item.external_id,
            kind=ArticleKind.RELEASE,
            canonical_url=item.url,
            title=self._optional_string(payload, "name") or tag_name or item.external_id,
            content=self._optional_string(payload, "body"),
            published_at=self._parse_datetime(published),
            updated_at=self._parse_datetime(updated) if updated else None,
            authors=authors,
            tags=tags,
            license=license_name if isinstance(license_name, str) else None,
            metadata=metadata,
        )

    async def _prepare_cursor(self, cursor: AdapterCursor | None) -> _GitHubCursor:
        previous = _GitHubCursor.model_validate(cursor.value) if cursor else _GitHubCursor()
        if previous.completed or not previous.repositories:
            repositories = await self.discover_repositories()
            return _GitHubCursor(repositories=repositories, etags=previous.etags)
        if previous.repository_index > len(previous.repositories):
            raise ValueError("GitHub cursor repository index is out of range")
        return previous

    async def _repository_data(
        self,
        repository: str,
        state: _GitHubCursor,
    ) -> dict[str, JsonValue]:
        if repository in self._repository_metadata:
            return self._repository_metadata[repository]
        try:
            response = await self._request(f"{self.config.api_url}repos/{repository}")
            metadata = JSON_OBJECT.validate_python(response.json())
        except GitHubRateLimitError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            self._record_error(state, repository, error, operation="metadata")
            metadata = {"full_name": repository, "topics": []}
        self._repository_metadata[repository] = metadata
        return metadata

    async def _request(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        allow_not_modified: bool = False,
    ) -> httpx.Response:
        for attempt in range(self.config.max_retries + 1):
            await self._respect_request_interval()
            try:
                request_headers = {**self._default_headers, **(headers or {})}
                response = await self._client.get(url, params=params, headers=request_headers)
            except httpx.TransportError as error:
                if attempt >= self.config.max_retries:
                    raise
                delay = self.config.retry_backoff_seconds * (2**attempt)
                logger.warning("GitHub transport error; retrying in %.1fs: %s", delay, error)
                await self._sleep(delay)
                continue

            if allow_not_modified and response.status_code == 304:
                return response
            if self._is_rate_limited(response):
                delay = self._rate_limit_delay(response, attempt)
                if attempt >= self.config.max_retries:
                    raise GitHubRateLimitError(
                        f"GitHub rate limit exhausted after {attempt + 1} attempts"
                    )
                logger.warning(
                    "GitHub rate limit response %s; retrying in %.1fs",
                    response.status_code,
                    delay,
                )
                await self._sleep(delay)
                continue
            if response.status_code >= 500:
                if attempt >= self.config.max_retries:
                    response.raise_for_status()
                delay = self.config.retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "GitHub server response %s; retrying in %.1fs",
                    response.status_code,
                    delay,
                )
                await self._sleep(delay)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("GitHub request retry loop exited unexpectedly")

    def _rate_limit_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self.config.secondary_limit_wait_seconds * (2**attempt)
        elif response.headers.get("x-ratelimit-remaining") == "0":
            try:
                reset = float(response.headers["x-ratelimit-reset"])
                delay = max(0, reset - self._epoch_clock())
            except (KeyError, ValueError):
                delay = self.config.secondary_limit_wait_seconds * (2**attempt)
        else:
            delay = self.config.secondary_limit_wait_seconds * (2**attempt)
        return min(delay, self.config.max_rate_limit_wait_seconds)

    @staticmethod
    def _is_rate_limited(response: httpx.Response) -> bool:
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        if (
            response.headers.get("retry-after")
            or response.headers.get("x-ratelimit-remaining") == "0"
        ):
            return True
        try:
            message = str(response.json().get("message", ""))
        except (ValueError, AttributeError):
            return False
        return "rate limit" in message.casefold()

    async def _respect_request_interval(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self.config.request_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                await self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _collected_item(
        self,
        repository: str,
        release: dict[str, JsonValue],
        metadata: dict[str, JsonValue],
    ) -> CollectedItem:
        release_id = self._required_integer(release, "id")
        url = self._required_string(release, "html_url")
        payload = dict(release)
        payload["repository"] = metadata
        return CollectedItem(
            external_id=f"{repository.casefold()}:{release_id}",
            url=AnyHttpUrl(url),
            payload=payload,
            fetched_at=self._clock(),
        )

    def _include_release(self, release: dict[str, JsonValue]) -> bool:
        if not self.config.include_drafts and release.get("draft") is True:
            return False
        return self.config.include_prereleases or release.get("prerelease") is not True

    def _next_link(self, value: str | None) -> str | None:
        if value is None:
            return None
        api_host = urlparse(str(self.config.api_url)).netloc
        for part in value.split(","):
            segments = [segment.strip() for segment in part.split(";")]
            if len(segments) < 2 or 'rel="next"' not in segments[1:]:
                continue
            candidate = segments[0].removeprefix("<").removesuffix(">")
            parsed = urlparse(candidate)
            if parsed.scheme != "https" or parsed.netloc != api_host:
                raise ValueError("GitHub pagination link points outside the configured API host")
            return candidate
        return None

    @staticmethod
    def _append_repositories(
        repositories: list[str],
        seen: set[str],
        values: list[dict[str, JsonValue]],
    ) -> None:
        for value in values:
            full_name = value.get("full_name")
            if isinstance(full_name, str) and full_name.casefold() not in seen:
                repositories.append(full_name)
                seen.add(full_name.casefold())

    @staticmethod
    def _advance_repository(state: _GitHubCursor) -> None:
        state.repository_index += 1
        state.next_url = None

    @staticmethod
    def _record_error(
        state: _GitHubCursor,
        repository: str,
        error: Exception,
        *,
        operation: str = "releases",
    ) -> None:
        message = str(error).replace("\n", " ")[:500]
        logger.warning("GitHub %s failed for %s: %s", operation, repository, message)
        state.errors.append({"repository": repository, "operation": operation, "error": message})
        state.errors = state.errors[-50:]

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("GitHub timestamp must include a timezone")
        return parsed

    @staticmethod
    def _required_string(payload: dict[str, JsonValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"GitHub payload field {key!r} must be a non-empty string")
        return value

    @staticmethod
    def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _required_integer(payload: dict[str, JsonValue], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"GitHub payload field {key!r} must be an integer")
        return value

    @staticmethod
    def _required_object(payload: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
        value = payload.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"GitHub payload field {key!r} must be an object")
        return value
