# AI Tech Radar backend

FastAPI backend for AI Tech Radar.

- Data model and adapter contract: [`docs/data-model.md`](docs/data-model.md)
- arXiv collector and sample command: [`docs/arxiv-collector.md`](docs/arxiv-collector.md)
- GitHub Releases collector: [`docs/github-releases-collector.md`](docs/github-releases-collector.md)
- Hugging Face Hub collector: [`docs/hugging-face-collector.md`](docs/hugging-face-collector.md)
- Manual radar editions and collection run records: [`docs/collection-scheduler.md`](docs/collection-scheduler.md)
- Normalization, deduplication, and event clustering: [`docs/normalization-and-clustering.md`](docs/normalization-and-clustering.md)
- AI classification, Chinese summaries, scoring, and evaluation: [`docs/ai-analysis.md`](docs/ai-analysis.md)
- Article listing, detail, topics, daily brief, and search API: [`docs/query-api.md`](docs/query-api.md)
- Run migrations: `alembic upgrade head`
- Run tests: `pytest`
