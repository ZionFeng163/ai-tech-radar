import hashlib
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import cast

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.collection.locking import source_run_lock
from app.db import SessionLocal
from app.domain import ArticleKind, SourceKind
from app.models import Article, ArticleIdentity, Author, EventCluster, RawItem, Source, Tag
from app.processing.config import ProcessingConfig
from app.processing.embeddings import (
    EMBEDDING_METHOD,
    best_match,
    embed_text,
    shared_terms,
    update_centroid,
)
from app.processing.text import (
    canonicalize_url,
    normalized_author_name,
    slugify_tag,
    title_fingerprint,
)


@dataclass(frozen=True, slots=True)
class IdentityKey:
    identity_type: str
    value: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.value.encode()).hexdigest()


@dataclass(slots=True)
class ProcessingSummary:
    processed: int = 0
    articles_created: int = 0
    exact_matches: int = 0
    clusters_created: int = 0
    clusters_joined: int = 0
    skipped: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def article_kind(source: Source, raw_item: RawItem) -> ArticleKind:
    if source.kind is SourceKind.ARXIV:
        return ArticleKind.PAPER
    if source.kind is SourceKind.GITHUB_RELEASES:
        return ArticleKind.RELEASE
    if source.kind is SourceKind.HUGGING_FACE:
        resource_type = raw_item.source_metadata.get("resource_type")
        if resource_type == "dataset" or raw_item.external_id.startswith("dataset:"):
            return ArticleKind.DATASET
        return ArticleKind.MODEL
    if source.kind is SourceKind.BLOG:
        return ArticleKind.BLOG_POST
    return ArticleKind.NEWS


def title_identity_value(kind: ArticleKind, fingerprint: str, metadata: dict[str, object]) -> str:
    scope: str | None = None
    repository = metadata.get("repository")
    if kind is ArticleKind.RELEASE and isinstance(repository, dict):
        full_name = repository.get("full_name")
        scope = full_name.casefold() if isinstance(full_name, str) else None
    if kind in {ArticleKind.MODEL, ArticleKind.DATASET}:
        repo_id = metadata.get("repo_id")
        scope = repo_id.casefold() if isinstance(repo_id, str) else None
    parts = [kind.value]
    if scope:
        parts.append(scope)
    parts.append(fingerprint)
    return ":".join(parts)


class NormalizationPipeline:
    def __init__(self, config: ProcessingConfig | None = None) -> None:
        self.config = config or ProcessingConfig()

    def run(self, *, limit: int | None = None) -> ProcessingSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        summary = ProcessingSummary()
        with source_run_lock("normalization") as acquired:
            if not acquired:
                summary.skipped = True
                return summary
            with SessionLocal() as session:
                statement = (
                    select(RawItem)
                    .options(selectinload(RawItem.source))
                    .where(RawItem.article_id.is_(None))
                    .order_by(RawItem.published_at.asc().nulls_last(), RawItem.fetched_at.asc())
                    .with_for_update(skip_locked=True)
                )
                if limit is not None:
                    statement = statement.limit(limit)
                for raw_item in session.scalars(statement):
                    self._process_raw_item(session, raw_item, summary)
                session.commit()
        return summary

    def _process_raw_item(
        self,
        session: Session,
        raw_item: RawItem,
        summary: ProcessingSummary,
    ) -> None:
        source = raw_item.source
        kind = article_kind(source, raw_item)
        title = raw_item.title or raw_item.external_id
        canonical_url = canonicalize_url(raw_item.url)
        fingerprint = title_fingerprint(title)
        identity_keys = [
            IdentityKey("source_external_id", f"{source.slug}:{raw_item.external_id}"),
            IdentityKey("canonical_url", canonical_url),
            IdentityKey(
                "title_fingerprint",
                title_identity_value(kind, fingerprint, raw_item.source_metadata),
            ),
        ]
        article, matched_types = self._find_exact_article(session, identity_keys)
        created = article is None
        embedding_input = (
            f"{title} {title} {(raw_item.body or '')[: self.config.content_characters]}"
        )
        embedding = embed_text(embedding_input, self.config.embedding_dimensions)

        if article is None:
            article = Article(
                kind=kind,
                canonical_url=canonical_url,
                title=title,
                content=raw_item.body,
                license=raw_item.license,
                published_at=raw_item.published_at or raw_item.fetched_at,
                content_hash=self._article_content_hash(title, raw_item.body),
                title_fingerprint=fingerprint,
                embedding=embedding,
                source_metadata={
                    "normalization": {
                        "version": 1,
                        "embedding_method": EMBEDDING_METHOD,
                    }
                },
            )
            session.add(article)
            session.flush()
            summary.articles_created += 1
        else:
            self._enrich_article(article, raw_item)
            summary.exact_matches += 1

        self._ensure_identities(session, article, identity_keys)
        self._ensure_authors(session, article, raw_item)
        self._ensure_tags(session, article, raw_item)
        raw_item.article = article

        if article.event_cluster is None:
            joined = self._assign_event_cluster(session, article)
            if joined:
                summary.clusters_joined += 1
            else:
                summary.clusters_created += 1

        normalization = cast(dict[str, object], article.source_metadata.get("normalization", {}))
        article.source_metadata = {
            **article.source_metadata,
            "normalization": {
                **normalization,
                "exact_match": not created,
                "matched_identity_types": matched_types,
                "cluster_id": str(article.event_cluster.id) if article.event_cluster else None,
            },
        }
        session.flush()
        summary.processed += 1

    @staticmethod
    def _find_exact_article(
        session: Session, keys: list[IdentityKey]
    ) -> tuple[Article | None, list[str]]:
        predicates = [
            and_(
                ArticleIdentity.identity_type == key.identity_type,
                ArticleIdentity.identity_hash == key.digest,
            )
            for key in keys
        ]
        identities = list(
            session.scalars(
                select(ArticleIdentity)
                .options(selectinload(ArticleIdentity.article))
                .where(or_(*predicates))
            )
        )
        if not identities:
            return None, []
        identities.sort(
            key=lambda identity: (identity.article.created_at, str(identity.article_id))
        )
        article = identities[0].article
        matched = sorted(
            identity.identity_type for identity in identities if identity.article_id == article.id
        )
        return article, matched

    @staticmethod
    def _ensure_identities(session: Session, article: Article, keys: list[IdentityKey]) -> None:
        existing = {
            (identity.identity_type, identity.identity_hash)
            for identity in session.scalars(
                select(ArticleIdentity).where(
                    or_(
                        *[
                            and_(
                                ArticleIdentity.identity_type == key.identity_type,
                                ArticleIdentity.identity_hash == key.digest,
                            )
                            for key in keys
                        ]
                    )
                )
            )
        }
        for key in keys:
            if (key.identity_type, key.digest) in existing:
                continue
            article.identities.append(
                ArticleIdentity(
                    identity_type=key.identity_type,
                    identity_hash=key.digest,
                    identity_value=key.value,
                )
            )

    @staticmethod
    def _enrich_article(article: Article, raw_item: RawItem) -> None:
        if raw_item.body and len(raw_item.body) > len(article.content or ""):
            article.content = raw_item.body
            article.content_hash = NormalizationPipeline._article_content_hash(
                article.title, raw_item.body
            )
        if article.license is None:
            article.license = raw_item.license
        published_at = raw_item.published_at or raw_item.fetched_at
        article.published_at = min(article.published_at, published_at)

    @staticmethod
    def _article_content_hash(title: str, content: str | None) -> str:
        value = f"{title.strip()}\n{(content or '').strip()}"
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _ensure_authors(session: Session, article: Article, raw_item: RawItem) -> None:
        existing_names = {author.normalized_name for author in article.authors}
        for value in raw_item.authors:
            name = value.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            normalized = normalized_author_name(name)
            if normalized in existing_names:
                continue
            author = session.scalar(select(Author).where(Author.normalized_name == normalized))
            if author is None:
                url = value.get("url")
                external_ids = value.get("external_ids", {})
                author = Author(
                    name=name.strip(),
                    normalized_name=normalized,
                    url=url if isinstance(url, str) else None,
                    external_ids=external_ids if isinstance(external_ids, dict) else {},
                )
                session.add(author)
            article.authors.append(author)
            existing_names.add(normalized)

    @staticmethod
    def _ensure_tags(session: Session, article: Article, raw_item: RawItem) -> None:
        values: list[str] = []
        for key in ("categories", "tags"):
            raw_values = raw_item.source_metadata.get(key, [])
            if isinstance(raw_values, list):
                values.extend(value for value in raw_values if isinstance(value, str))
        for key in ("tag_name", "pipeline_tag", "resource_type", "primary_category"):
            value = raw_item.source_metadata.get(key)
            if isinstance(value, str):
                values.append(value)
        repository = raw_item.source_metadata.get("repository")
        if isinstance(repository, dict):
            topics = repository.get("topics", [])
            if isinstance(topics, list):
                values.extend(value for value in topics if isinstance(value, str))

        existing_slugs = {tag.slug for tag in article.tags}
        for name in dict.fromkeys(value.strip() for value in values if value.strip()):
            slug = slugify_tag(name)
            if slug in existing_slugs:
                continue
            tag = session.scalar(select(Tag).where(Tag.slug == slug))
            if tag is None:
                tag = Tag(slug=slug, name=name)
                session.add(tag)
            article.tags.append(tag)
            existing_slugs.add(slug)

    def _assign_event_cluster(self, session: Session, article: Article) -> bool:
        window = timedelta(hours=self.config.event_window_hours)
        candidates = list(
            session.scalars(
                select(EventCluster)
                .where(
                    EventCluster.last_published_at >= article.published_at - window,
                    EventCluster.first_published_at <= article.published_at + window,
                )
                .order_by(EventCluster.last_published_at.desc())
                .limit(self.config.candidate_limit)
            )
        )
        match = best_match(
            article.embedding,
            [cluster.centroid for cluster in candidates],
            self.config.similarity_threshold,
        )
        if match is None:
            cluster = EventCluster(
                label=article.title,
                centroid=article.embedding,
                member_count=1,
                first_published_at=article.published_at,
                last_published_at=article.published_at,
                explanation={
                    "method": EMBEDDING_METHOD,
                    "threshold": self.config.similarity_threshold,
                    "reason": "no_candidate_above_threshold",
                },
            )
            session.add(cluster)
            session.flush()
            article.event_cluster = cluster
            return False

        index, score = match
        cluster = candidates[index]
        previous_count = cluster.member_count
        cluster.centroid = update_centroid(cluster.centroid, previous_count, article.embedding)
        cluster.member_count = previous_count + 1
        cluster.first_published_at = min(cluster.first_published_at, article.published_at)
        cluster.last_published_at = max(cluster.last_published_at, article.published_at)
        cluster.explanation = {
            "method": EMBEDDING_METHOD,
            "threshold": self.config.similarity_threshold,
            "last_match_score": round(score, 6),
            "last_shared_terms": shared_terms(cluster.label, article.title),
            "last_matched_title": article.title,
        }
        article.event_cluster = cluster
        return True
