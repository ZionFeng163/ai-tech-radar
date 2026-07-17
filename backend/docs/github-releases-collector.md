# GitHub Releases collector

The GitHub Releases adapter collects configured AI project releases into `RawItem`. It uses
GitHub REST API version `2026-03-10` and can run anonymously or with a `GITHUB_TOKEN`.

Official references:

- [List releases](https://docs.github.com/en/rest/releases/releases)
- [API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)
- [Pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)
- [REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)

## Repository configuration

The default file is `backend/config/sources/github-releases.json` and contains ten AI-related
repositories. It supports three discovery inputs:

- `repositories`: exact `owner/repository` names
- `organizations`: recently updated repositories from each organization
- `topics`: recently updated repositories returned by GitHub repository search

Discovery results are de-duplicated case-insensitively and capped by
`max_discovered_repositories`. The access token is never stored in this JSON file or in source
configuration JSONB. Set it through the environment:

```bash
GITHUB_TOKEN=github_pat_... docker compose up -d backend
```

Without a token, public repository collection automatically uses GitHub's anonymous access.

## Incremental cursor and failures

The cursor records the resolved repository list, current repository, next page URL, per-repository
ETags, bounded errors, and whether a complete pass finished. A completed pass starts again at the
first repository and sends `If-None-Match`; a `304 Not Modified` response skips that repository.
Pagination follows GitHub's `Link` header and only accepts links on the configured API host.

Requests are serial and rate-limited locally. Transient transport and 5xx responses use bounded
exponential retry. For 403/429 rate limits, the adapter waits according to `Retry-After`, then
`X-RateLimit-Reset`, then the configured secondary-limit backoff. Exhausted global rate limits stop
the run. A single repository's non-rate-limit failure is logged in the cursor and does not prevent
later repositories from being collected.

The stable external ID is `<casefolded owner/repository>:<release id>`. PostgreSQL upsert on
`(source_id, external_id)` makes repeated collection safe. Repository stars, license, language,
topics, visibility and other repository API fields are stored with each release's source metadata.

## Bounded sample command

Collect three releases with the default configuration and persist them:

```bash
docker compose exec backend python -m app.sources.github_releases.sample --limit 3 --persist
```

Override the repository list for a focused sample:

```bash
docker compose exec backend python -m app.sources.github_releases.sample \
  --repository openai/openai-python \
  --repository huggingface/transformers \
  --limit 5 \
  --persist
```

`--organization` and `--topic` can also be repeated. The command prints a JSON summary and records
a `FetchRun` when persistence is enabled.
