# arXiv collector

The arXiv adapter collects Atom API results into `RawItem`. Article normalization and
enrichment remain a separate pipeline stage.

## Configuration

`ArxivConfig` supports:

- `categories`: arXiv category identifiers; defaults to `cs.AI`, `cs.LG`, `cs.CV`, and `cs.CL`
- `keywords`: optional phrases matched against all indexed fields
- `window_hours`: initial lookback window, default 24 hours
- `overlap_minutes`: overlap after a completed run, default 15 minutes
- `page_size`: maximum results per API page
- request interval, timeout, retry count, backoff, endpoint, and user agent

Category filters, keyword filters, and the submitted-date window are combined with `AND`.
Values within each category or keyword group are combined with `OR`.

## Cursor and idempotency

While pagination is active, the cursor stores a fixed `window_start`, `window_end`, and
`offset`. This prevents the result window from moving between pages. After the last page, the
cursor becomes a `watermark` at the completed window end. The next run starts slightly before
that watermark according to `overlap_minutes`.

The external ID is the stable arXiv identifier without its `vN` suffix. Versioned ID, version
number, published time, updated time, categories, PDF URL, DOI, and other provider fields stay
in JSONB. The database unique key `(source_id, external_id)` and PostgreSQL upsert make overlap
and repeated collection safe.

## Bounded sample command

Dry run:

```bash
docker compose exec backend python -m app.sources.arxiv.sample --limit 3
```

Persist to PostgreSQL and advance the source cursor:

```bash
docker compose exec backend python -m app.sources.arxiv.sample --limit 3 --persist
```

Filters can be repeated:

```bash
docker compose exec backend python -m app.sources.arxiv.sample \
  --limit 10 \
  --category cs.AI \
  --category cs.LG \
  --keyword "large language model" \
  --window-hours 48 \
  --persist
```

The command prints a JSON summary and creates a `FetchRun` when persistence is enabled. A
failed persistent run is recorded with a bounded error summary.
