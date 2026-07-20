from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.processing.config import ProcessingConfig
from app.processing.embeddings import cosine_similarity, embed_text

DEFAULT_EVALUATION_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "evaluation" / "dedup-samples.json"
)


class EvaluationSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title_a: str
    title_b: str
    same_event: bool


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    samples: list[EvaluationSample]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    threshold: float
    samples: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    cases: list[dict[str, object]]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate(
    config: ProcessingConfig,
    path: Path = DEFAULT_EVALUATION_PATH,
) -> EvaluationResult:
    dataset = EvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))
    tp = fp = tn = fn = 0
    cases: list[dict[str, object]] = []
    for sample in dataset.samples:
        first = embed_text(sample.title_a, config.embedding_dimensions)
        second = embed_text(sample.title_b, config.embedding_dimensions)
        score = cosine_similarity(first, second)
        predicted = score >= config.similarity_threshold
        if predicted and sample.same_event:
            tp += 1
        elif predicted:
            fp += 1
        elif sample.same_event:
            fn += 1
        else:
            tn += 1
        cases.append(
            {
                "id": sample.id,
                "score": round(score, 4),
                "expected": sample.same_event,
                "predicted": predicted,
            }
        )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return EvaluationResult(
        threshold=config.similarity_threshold,
        samples=len(dataset.samples),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        cases=cases,
    )
