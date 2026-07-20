from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app.db import Base
from app.domain import AnalysisRunStatus, ArticleKind
from app.models import AnalysisRun, Article, ArticleIdentity, EventCluster, RawItem


def test_all_domain_models_are_registered() -> None:
    configure_mappers()

    assert {
        "sources",
        "raw_items",
        "articles",
        "authors",
        "tags",
        "fetch_runs",
        "event_clusters",
        "article_identities",
        "article_authors",
        "article_tags",
        "analysis_runs",
    } <= set(Base.metadata.tables)


def test_raw_item_has_stable_source_external_id_constraint() -> None:
    unique_constraints = [
        constraint
        for constraint in RawItem.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uq_raw_items_source_external_id"
        and [column.name for column in constraint.columns] == ["source_id", "external_id"]
        for constraint in unique_constraints
    )


def test_article_kinds_cover_mvp_content_types() -> None:
    supported = {kind.value for kind in ArticleKind}

    assert {"paper", "code_repository", "release", "blog_post"} <= supported
    assert Article.__table__.c.kind.type.name == "article_kind"


def test_article_identity_and_event_cluster_schema_support_deduplication() -> None:
    identity_constraints = [
        constraint
        for constraint in ArticleIdentity.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uq_article_identities_key" for constraint in identity_constraints
    )
    assert Article.__table__.c.event_cluster_id.references(EventCluster.__table__.c.id)
    assert Article.__table__.c.title_fingerprint.index is True


def test_analysis_attempts_reference_articles_and_keep_audit_fields() -> None:
    assert AnalysisRun.__table__.c.article_id.references(Article.__table__.c.id)
    assert AnalysisRun.__table__.c.status.type.name == "analysis_run_status"
    assert {status.value for status in AnalysisRunStatus} == {"running", "success", "failed"}
    assert {"request_payload", "raw_response", "parsed_output", "error_summary"} <= {
        column.name for column in AnalysisRun.__table__.columns
    }
