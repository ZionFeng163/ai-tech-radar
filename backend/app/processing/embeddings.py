import hashlib
import math
from collections import defaultdict

from app.processing.text import normalize_title

EMBEDDING_METHOD = "feature_hash_v1"


def significant_terms(value: str) -> list[str]:
    return [term for term in normalize_title(value).split() if len(term) > 1 or not term.isascii()]


def shared_terms(first: str, second: str) -> list[str]:
    return sorted(set(significant_terms(first)) & set(significant_terms(second)))[:20]


def _english_stem(term: str) -> str:
    if not term.isascii() or len(term) < 5:
        return term
    for suffix in ("ing", "ed", "es", "s"):
        if term.endswith(suffix) and len(term) - len(suffix) >= 4:
            term = term[: -len(suffix)]
            break
    return term[:-1] if term.endswith("e") and len(term) > 4 else term


def _features(value: str) -> dict[str, float]:
    normalized = normalize_title(value)
    terms = significant_terms(value)
    features: defaultdict[str, float] = defaultdict(float)
    for term in terms:
        features[f"word:{term}"] += 2.0
        stem = _english_stem(term)
        if stem != term:
            features[f"stem:{stem}"] += 1.5
    stems = [_english_stem(term) for term in terms]
    for left, right in zip(stems, stems[1:], strict=False):
        features[f"bigram:{left}:{right}"] += 1.0
    compact = normalized.replace(" ", "")
    for index in range(max(0, len(compact) - 2)):
        features[f"char3:{compact[index : index + 3]}"] += 0.2
    return dict(features)


def embed_text(value: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for feature, weight in _features(value).items():
        digest = hashlib.sha256(feature.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * weight
    return normalize_vector(vector)


def normalize_vector(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return list(vector)
    return [value / magnitude for value in vector]


def cosine_similarity(first: list[float], second: list[float]) -> float:
    if len(first) != len(second):
        raise ValueError("embedding dimensions must match")
    return sum(left * right for left, right in zip(first, second, strict=True))


def update_centroid(centroid: list[float], member_count: int, value: list[float]) -> list[float]:
    if not centroid or member_count < 1:
        return list(value)
    if len(centroid) != len(value):
        raise ValueError("embedding dimensions must match")
    combined = [
        (old * member_count + new) / (member_count + 1)
        for old, new in zip(centroid, value, strict=True)
    ]
    return normalize_vector(combined)


def best_match(
    value: list[float], candidates: list[list[float]], threshold: float
) -> tuple[int, float] | None:
    scored = [
        (index, cosine_similarity(value, candidate)) for index, candidate in enumerate(candidates)
    ]
    if not scored:
        return None
    best = max(scored, key=lambda item: item[1])
    return best if best[1] >= threshold else None
