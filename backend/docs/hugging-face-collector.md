# Hugging Face Hub collector

The Hugging Face adapter incrementally collects recently updated models and datasets into
`RawItem`. Public resources work anonymously; setting `HF_TOKEN` enables authenticated Hub API
requests.

Official references:

- [HfApi list_models and list_datasets](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api)
- [Hub rate limits](https://huggingface.co/docs/hub/en/rate-limits)

## Configuration

The default file is `backend/config/sources/hugging-face.json`. It enables models and datasets and
includes these model pipeline tasks:

- `text-generation`
- `image-text-to-text`
- `automatic-speech-recognition`

`model_tasks` maps to the Hub `pipeline_tag` filter. `dataset_filters` accepts Hub dataset tags,
for example `task_categories:text-classification`. `authors` and `organizations` both map to Hub
author filtering; keeping both empty collects across the public Hub. The query results are sorted
by `lastModified` descending.

The token is never written to the JSON configuration or source configuration JSONB:

```bash
HF_TOKEN=hf_... docker compose up -d backend
```

## Cursor and failure behavior

Each model-task/dataset-filter/author combination becomes an independent query. The cursor stores:

- the stable query list and current query index
- the opaque next URL from the Hub `Link` header
- a completed `lastModified` watermark per query
- the maximum timestamp seen while the current query is still paginating
- bounded query and item errors

Pagination links must remain on the configured Hub host. A completed query advances its watermark;
the next run reads a small overlapping time window so equal-time boundary records are safely
upserted. The stable IDs are `model:<repo_id>` and `dataset:<repo_id>`.

Requests are serial and locally rate-limited. Transport and 5xx failures use bounded exponential
retry. A 429 response uses `Retry-After` first, then the Hub `RateLimit` reset duration, then a
configured fallback. Exhausted rate limits stop the run. A failed query is recorded and later
queries continue; a malformed individual item is recorded and skipped without losing valid items
in the same page.

The adapter saves description when exposed by the Hub, tags, pipeline task, license, downloads,
likes, SHA, author, timestamps, gating/privacy state, library name and complete `cardData` metadata.

## Bounded sample command

Collect and persist three recently updated Hub items:

```bash
docker compose exec backend python -m app.sources.hugging_face.sample --limit 3 --persist
```

Collect a focused model sample:

```bash
docker compose exec backend python -m app.sources.hugging_face.sample \
  --resource-type model \
  --model-task text-generation \
  --organization openbmb \
  --window-hours 48 \
  --limit 5 \
  --persist
```

`--model-task`, `--dataset-filter`, `--author`, `--organization`, and `--resource-type` can be
repeated. A persistent run creates a `FetchRun`; isolated errors make the run `partial`, while a
global rate-limit or unexpected error makes it `failed`.
