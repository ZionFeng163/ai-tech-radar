import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.domain import ArticleKind
from app.sources.github_releases import GitHubReleasesAdapter, GitHubReleasesConfig

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):  # type: ignore[no-untyped-def]
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_default_config_contains_ten_repositories_and_file_is_loadable() -> None:
    default = GitHubReleasesConfig()
    from_file = GitHubReleasesConfig.from_file(
        Path(__file__).parents[1] / "config" / "sources" / "github-releases.json"
    )

    assert len(default.repositories) >= 10
    assert len(from_file.repositories) >= 10
    assert len(set(value.casefold() for value in from_file.repositories)) == len(
        from_file.repositories
    )

    authenticated = GitHubReleasesConfig(token="do-not-store")
    assert "token" not in authenticated.persisted_config()
    assert authenticated.persisted_config()["authentication"] == "token"


def test_fetch_normalizes_release_and_uses_etag_on_next_run() -> None:
    release_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal release_calls
        assert request.headers["accept"] == "application/vnd.github+json"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        assert request.headers["authorization"] == "Bearer test-token"
        if request.url.path == "/repos/acme/radar":
            return httpx.Response(
                200,
                json=load_json("github_repository.json"),
                request=request,
            )
        assert request.url.path == "/repos/acme/radar/releases"
        release_calls += 1
        if release_calls == 2:
            assert request.headers["if-none-match"] == 'W/"release-etag"'
            return httpx.Response(304, request=request)
        return httpx.Response(
            200,
            json=load_json("github_releases.json"),
            headers={"ETag": 'W/"release-etag"'},
            request=request,
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = GitHubReleasesAdapter(
                GitHubReleasesConfig(
                    token="test-token",
                    repositories=["acme/radar"],
                    request_interval_seconds=0,
                ),
                client=client,
            )
            first = await adapter.fetch(limit=10)
            normalized = adapter.normalize(first.items[0])
            second = await adapter.fetch(first.next_cursor, limit=10)

        assert first.has_more is False
        assert first.items[0].external_id == "acme/radar:987654"
        assert normalized.kind is ArticleKind.RELEASE
        assert normalized.title == "acme/radar · Radar v1.2.0"
        assert normalized.license == "Apache-2.0"
        assert normalized.tags == [
            "artificial-intelligence",
            "machine-learning",
            "v1.2.0",
        ]
        assert normalized.metadata["repository"]["stargazers_count"] == 2048
        assert normalized.authors[0].name == "octocat"
        assert second.items == []
        assert second.next_cursor.value["completed"] is True

    asyncio.run(scenario())


def test_link_pagination_and_repository_failure_isolation() -> None:
    release = load_json("github_releases.json")[0]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/one":
            metadata = load_json("github_repository.json")
            metadata["full_name"] = "acme/one"
            return httpx.Response(200, json=metadata, request=request)
        if path == "/repos/acme/one/releases" and request.url.params.get("page") == "2":
            second = {**release, "id": 2, "tag_name": "v2", "name": "Version 2"}
            return httpx.Response(200, json=[second], request=request)
        if path == "/repos/acme/one/releases":
            first = {**release, "id": 1, "tag_name": "v1", "name": "Version 1"}
            return httpx.Response(
                200,
                json=[first],
                headers={
                    "Link": (
                        "<https://api.github.com/repos/acme/one/releases?per_page=1&page=2>; "
                        'rel="next"'
                    )
                },
                request=request,
            )
        if path == "/repos/acme/two/releases":
            return httpx.Response(404, json={"message": "Not Found"}, request=request)
        raise AssertionError(f"unexpected request: {request.url}")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = GitHubReleasesAdapter(
                GitHubReleasesConfig(
                    repositories=["acme/one", "acme/two"],
                    page_size=1,
                    request_interval_seconds=0,
                ),
                client=client,
            )
            first = await adapter.fetch(limit=1)
            second = await adapter.fetch(first.next_cursor, limit=1)
            final = await adapter.fetch(second.next_cursor, limit=1)

        assert [first.items[0].external_id, second.items[0].external_id] == [
            "acme/one:1",
            "acme/one:2",
        ]
        assert first.has_more is True
        assert second.has_more is True
        assert final.has_more is False
        assert final.items == []
        assert final.next_cursor.value["errors"][0]["repository"] == "acme/two"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "headers", "expected_delay"),
    [
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "110"}, 10.0),
        (429, {"Retry-After": "7"}, 7.0),
    ],
)
def test_rate_limit_responses_wait_then_retry(
    status: int,
    headers: dict[str, str],
    expected_delay: float,
) -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                status,
                json={"message": "API rate limit exceeded"},
                headers=headers,
                request=request,
            )
        return httpx.Response(200, json=[], request=request)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = GitHubReleasesAdapter(
                GitHubReleasesConfig(
                    repositories=["acme/radar"],
                    request_interval_seconds=0,
                    max_retries=1,
                ),
                client=client,
                epoch_clock=lambda: 100,
                sleep=sleep,
            )
            result = await adapter.fetch()
            assert result.items == []

    asyncio.run(scenario())
    assert calls == 2
    assert delays == [expected_delay]


def test_organization_and_topic_discovery_deduplicates_repositories() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/orgs/acme/repos":
            return httpx.Response(200, json=[{"full_name": "acme/from-org"}], request=request)
        if request.url.path == "/search/repositories":
            assert request.url.params["q"] == "topic:machine-learning"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"full_name": "acme/from-topic"},
                        {"full_name": "ACME/FROM-ORG"},
                    ]
                },
                request=request,
            )
        raise AssertionError(f"unexpected request: {request.url}")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = GitHubReleasesAdapter(
                GitHubReleasesConfig(
                    repositories=["acme/explicit"],
                    organizations=["acme"],
                    topics=["machine-learning"],
                    request_interval_seconds=0,
                ),
                client=client,
            )
            repositories = await adapter.discover_repositories()
        assert repositories == ["acme/explicit", "acme/from-org", "acme/from-topic"]

    asyncio.run(scenario())
