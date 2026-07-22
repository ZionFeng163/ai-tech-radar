from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.cursor import PageCursor, decode_cursor, encode_cursor
from app.api.dependencies import get_session
from app.db import engine
from app.domain import ArticleKind, SourceKind
from app.main import app
from app.models import Article, RawItem, Source


def test_openapi_exposes_stable_article_query_contract() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()

    assert {
        "/articles",
        "/articles/{article_id}",
        "/topics",
        "/daily-brief",
        "/search",
        "/radar-editions",
        "/radar-editions/{edition_id}",
    } <= {
        path for path in schema["paths"]
    }
    article_parameters = {
        parameter["name"] for parameter in schema["paths"]["/articles"]["get"]["parameters"]
    }
    assert {
        "date_from",
        "date_to",
        "edition",
        "source",
        "category",
        "importance_min",
        "open_source_status",
        "cursor",
        "limit",
    } <= article_parameters


def test_cursor_round_trip_and_invalid_cursor_response() -> None:
    expected = PageCursor(
        published_at=datetime(2026, 7, 20, 1, 2, 3, tzinfo=UTC),
        article_id=uuid4(),
        score_key=123,
    )
    assert decode_cursor(encode_cursor(expected)) == expected

    response = TestClient(app).get("/articles", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid pagination cursor"


def test_all_responses_include_basic_performance_headers() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.headers["server-timing"].startswith("app;dur=")
    assert float(response.headers["x-response-time-ms"]) >= 0


@dataclass(frozen=True, slots=True)
class SeededAPI:
    client: TestClient
    source_slug: str
    article_ids: tuple[UUID, UUID, UUID]
    query_token: str
    day: date


@pytest.fixture
def seeded_api() -> SeededAPI:
    if os.getenv("RUN_DATABASE_TESTS") != "1":
        pytest.skip("set RUN_DATABASE_TESTS=1 to run PostgreSQL API integration tests")

    connection = engine.connect()
    transaction = connection.begin()
    seed_session = Session(bind=connection)
    suffix = uuid4().hex
    source = Source(
        slug=f"api-source-{suffix}",
        name="API Integration Source",
        kind=SourceKind.OTHER,
        base_url="https://example.test",
    )
    other_source = Source(
        slug=f"api-other-{suffix}",
        name="Other Integration Source",
        kind=SourceKind.BLOG,
        base_url="https://other.example.test",
    )
    query_token = f"radarapitest{suffix}"
    published = datetime(2026, 7, 19, 2, tzinfo=UTC)
    articles = (
        Article(
            kind=ArticleKind.PAPER,
            canonical_url=f"https://example.test/{suffix}/transformer",
            title=f"{query_token} Transformer Runtime",
            content=f"The {query_token} system improves transformer deployment.",
            summary="一个用于验证 API 搜索、筛选与分页行为的基础模型测试条目。",
            primary_category="foundation_models",
            analysis_tags=["transformer", "runtime"],
            importance_score=9,
            credibility_score=8,
            open_source_status="open",
            analysis={"schema_version": "1.0"},
            analysis_schema_version="1.0",
            published_at=published,
        ),
        Article(
            kind=ArticleKind.DATASET,
            canonical_url=f"https://example.test/{suffix}/speech",
            title="Efficient Speech Dataset",
            content=f"A partially open {query_token} audio dataset for speech recognition.",
            summary="用于语音识别评测的数据集。",
            primary_category="speech_audio",
            analysis_tags=["speech", "dataset"],
            importance_score=7,
            credibility_score=7,
            open_source_status="partial",
            analysis={"schema_version": "1.0"},
            analysis_schema_version="1.0",
            published_at=published - timedelta(hours=1),
        ),
        Article(
            kind=ArticleKind.NEWS,
            canonical_url=f"https://other.example.test/{suffix}/robot",
            title="Closed Robot API",
            content="A proprietary robotics API.",
            summary="机器人商业 API 发布。",
            primary_category="robotics",
            analysis_tags=["robotics"],
            importance_score=8,
            credibility_score=6,
            open_source_status="closed",
            analysis={"schema_version": "1.0"},
            analysis_schema_version="1.0",
            published_at=published - timedelta(days=1),
        ),
    )
    seed_session.add_all([source, other_source, *articles])
    seed_session.flush()
    seed_session.add_all(
        [
            _raw_item(source, articles[0], f"{suffix}-1"),
            _raw_item(source, articles[1], f"{suffix}-2"),
            _raw_item(other_source, articles[2], f"{suffix}-3"),
        ]
    )
    seed_session.flush()

    def override_session():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            yield SeededAPI(
                client=client,
                source_slug=source.slug,
                article_ids=tuple(article.id for article in articles),
                query_token=query_token,
                day=published.date(),
            )
    finally:
        app.dependency_overrides.pop(get_session, None)
        seed_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _raw_item(source: Source, article: Article, external_id: str) -> RawItem:
    return RawItem(
        source=source,
        article=article,
        external_id=external_id,
        url=article.canonical_url or "https://example.test/item",
        title=article.title,
        body=article.content,
        published_at=article.published_at,
        raw_payload={"test": True},
    )


def test_articles_support_filters_and_cursor_pagination(seeded_api: SeededAPI) -> None:
    params = {
        "source": seeded_api.source_slug,
        "date_from": seeded_api.day.isoformat(),
        "date_to": seeded_api.day.isoformat(),
        "limit": 1,
    }
    first = seeded_api.client.get("/articles", params=params)

    assert first.status_code == 200
    first_payload = first.json()
    assert len(first_payload["items"]) == 1
    assert first_payload["page"]["has_more"] is True
    assert first_payload["page"]["query_ms"] < 1_000
    assert first_payload["page"]["next_cursor"]

    second = seeded_api.client.get(
        "/articles",
        params={**params, "cursor": first_payload["page"]["next_cursor"]},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert len(second_payload["items"]) == 1
    assert second_payload["items"][0]["id"] != first_payload["items"][0]["id"]
    assert second_payload["page"]["has_more"] is False

    filtered = seeded_api.client.get(
        "/articles",
        params={
            "source": seeded_api.source_slug,
            "category": "foundation_models",
            "importance_min": 8,
            "open_source_status": "open",
        },
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [str(seeded_api.article_ids[0])]


def test_article_detail_topics_daily_brief_and_search(seeded_api: SeededAPI) -> None:
    detail = seeded_api.client.get(f"/articles/{seeded_api.article_ids[0]}")
    assert detail.status_code == 200
    assert detail.json()["analysis_schema_version"] == "1.0"
    assert detail.json()["sources"][0]["slug"] == seeded_api.source_slug

    topics = seeded_api.client.get("/topics", params={"source": seeded_api.source_slug})
    assert topics.status_code == 200
    assert {item["category"] for item in topics.json()["items"]} == {
        "foundation_models",
        "speech_audio",
    }

    brief = seeded_api.client.get(
        "/daily-brief",
        params={"date": seeded_api.day.isoformat(), "source": seeded_api.source_slug},
    )
    assert brief.status_code == 200
    assert brief.json()["total_articles"] == 2
    assert brief.json()["top_articles"][0]["importance_score"] == 9
    assert brief.json()["timezone"] == "Asia/Shanghai"

    first_search = seeded_api.client.get(
        "/search",
        params={"q": seeded_api.query_token, "source": seeded_api.source_slug, "limit": 1},
    )
    assert first_search.status_code == 200
    assert first_search.json()["page"]["has_more"] is True
    assert first_search.json()["page"]["next_cursor"]

    second_search = seeded_api.client.get(
        "/search",
        params={
            "q": seeded_api.query_token,
            "source": seeded_api.source_slug,
            "limit": 1,
            "cursor": first_search.json()["page"]["next_cursor"],
        },
    )
    assert second_search.status_code == 200
    assert second_search.json()["items"][0]["id"] != first_search.json()["items"][0]["id"]
    assert second_search.json()["page"]["has_more"] is False

    filtered_search = seeded_api.client.get(
        "/search",
        params={
            "q": seeded_api.query_token,
            "source": seeded_api.source_slug,
            "category": "foundation_models",
        },
    )
    assert filtered_search.status_code == 200
    assert [item["id"] for item in filtered_search.json()["items"]] == [
        str(seeded_api.article_ids[0])
    ]
    assert filtered_search.json()["items"][0]["search_score"] > 0
    assert filtered_search.json()["page"]["query_ms"] < 1_000

    missing = seeded_api.client.get(f"/articles/{uuid4()}")
    assert missing.status_code == 404
