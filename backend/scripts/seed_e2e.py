"""Insert one deterministic, idempotent article for the Docker end-to-end check."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.domain import ArticleKind, SourceKind
from app.models import Article, RawItem, Source

SOURCE_SLUG = "e2e-fixture"
EXTERNAL_ID = "radar-e2e-signal-v1"
CANONICAL_URL = "https://example.test/radar-e2e-signal-v1"
TITLE = "Radar E2E：可验证的高效推理信号"


def seed() -> str:
    with SessionLocal.begin() as session:
        source = session.scalar(select(Source).where(Source.slug == SOURCE_SLUG))
        if source is None:
            source = Source(
                slug=SOURCE_SLUG,
                name="E2E Fixture Source",
                kind=SourceKind.OTHER,
                base_url="https://example.test",
            )
            session.add(source)
            session.flush()

        raw_item = session.scalar(
            select(RawItem).where(
                RawItem.source_id == source.id,
                RawItem.external_id == EXTERNAL_ID,
            )
        )
        if raw_item is not None and raw_item.article_id is not None:
            return str(raw_item.article_id)

        article = session.scalar(select(Article).where(Article.canonical_url == CANONICAL_URL))
        if article is None:
            article = Article(
                kind=ArticleKind.PAPER,
                canonical_url=CANONICAL_URL,
                title=TITLE,
                content="radar-e2e 展示从样例入库、API 查询到 Web 服务端渲染的完整链路。",
                summary="用于验证 AI Tech Radar 最小端到端链路的确定性技术信号。",
                primary_category="inference",
                analysis_tags=["radar-e2e", "inference"],
                importance_score=9.2,
                credibility_score=9.0,
                open_source_status="open",
                analysis={
                    "core_innovations": ["使用确定性样例贯通数据库、API 与 Web 页面。"],
                    "differences_from_prior_work": ["不依赖外部网络或第三方 API。"],
                    "application_scenarios": ["持续集成和本地发布前验收。"],
                    "why_it_matters": "任何链路故障都会返回非零退出状态和明确步骤。",
                },
                analysis_schema_version="1.0",
                analyzed_at=datetime.now(UTC),
                license="CC0-1.0",
                published_at=datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
                source_metadata={"fixture": True},
            )
            session.add(article)
            session.flush()

        if raw_item is None:
            raw_item = RawItem(
                source=source,
                article=article,
                external_id=EXTERNAL_ID,
                url=CANONICAL_URL,
                title=TITLE,
                body=article.content,
                published_at=article.published_at,
                source_metadata={"fixture": True},
                raw_payload={"fixture": True, "token": "radar-e2e"},
            )
            session.add(raw_item)
        elif raw_item.article_id is None:
            raw_item.article = article

        session.flush()
        return str(article.id)


if __name__ == "__main__":
    print(seed())
