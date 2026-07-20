from pathlib import Path

from pydantic import ValidationError

from app.domain import ArticleKind
from app.processing.config import ProcessingConfig
from app.processing.embeddings import best_match, cosine_similarity, embed_text, update_centroid
from app.processing.evaluation import evaluate
from app.processing.pipeline import IdentityKey, title_identity_value
from app.processing.text import canonicalize_url, normalize_title, title_fingerprint


def test_url_canonicalization_removes_tracking_and_arxiv_versions() -> None:
    assert (
        canonicalize_url(
            "HTTPS://export.arxiv.org/pdf/2607.01234v2.pdf?utm_source=newsletter#page=2"
        )
        == "https://arxiv.org/abs/2607.01234"
    )
    assert (
        canonicalize_url("https://Example.com/releases/?b=2&utm_medium=email&a=1")
        == "https://example.com/releases?a=1&b=2"
    )


def test_title_normalization_and_fingerprint_are_stable() -> None:
    first = "  RadarLM—7B: A &amp; Better_Model! "
    second = "radarlm 7b a & better model"

    assert normalize_title(first) == "radarlm 7b a better model"
    assert normalize_title(first) == normalize_title(second)
    assert title_fingerprint(first) == title_fingerprint(second)


def test_feature_embedding_selects_similar_event() -> None:
    config = ProcessingConfig()
    query = embed_text("PyTorch 3.0 release improves distributed training", 256)
    same = embed_text("PyTorch 3.0 released with better distributed training", 256)
    different = embed_text("Speech dataset adds multilingual labels", 256)

    match = best_match(query, [different, same], config.similarity_threshold)

    assert cosine_similarity(query, same) > cosine_similarity(query, different)
    assert match is not None
    assert match[0] == 1


def test_centroid_update_preserves_unit_vector() -> None:
    first = embed_text("RadarLM 7B model release", 256)
    second = embed_text("RadarLM 7B open model released", 256)
    centroid = update_centroid(first, 1, second)

    assert abs(sum(value * value for value in centroid) - 1) < 1e-9


def test_identity_hash_does_not_store_unbounded_value_in_unique_index() -> None:
    key = IdentityKey("canonical_url", "https://example.com/" + "long/" * 1_000)

    assert len(key.digest) == 64
    assert key.digest == IdentityKey(key.identity_type, key.value).digest


def test_release_title_identity_is_scoped_to_repository() -> None:
    fingerprint = title_fingerprint("v1.0.0")

    first = title_identity_value(
        ArticleKind.RELEASE, fingerprint, {"repository": {"full_name": "acme/one"}}
    )
    second = title_identity_value(
        ArticleKind.RELEASE, fingerprint, {"repository": {"full_name": "acme/two"}}
    )

    assert first != second


def test_offline_evaluation_sample_meets_baseline() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config" / "processing.json"
    evaluation_path = (
        Path(__file__).resolve().parents[1] / "config" / "evaluation" / "dedup-samples.json"
    )
    result = evaluate(ProcessingConfig.from_file(config_path), evaluation_path)

    assert result.samples == 6
    assert result.precision >= 0.8
    assert result.recall >= 0.8
    assert result.f1 >= 0.8


def test_similarity_threshold_is_configurable_and_validated() -> None:
    assert ProcessingConfig(similarity_threshold=0.75).similarity_threshold == 0.75

    try:
        ProcessingConfig(similarity_threshold=1.1)
    except ValidationError:
        pass
    else:
        raise AssertionError("thresholds above one must be rejected")
