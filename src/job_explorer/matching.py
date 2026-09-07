from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from docx import Document

from job_explorer.models import ResumeSpec


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class SentenceTransformerEncoder:
    def __init__(self, model: object) -> None:
        self._model = model

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]


def build_encoder(model_name: str) -> Encoder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required to match resumes. "
            "Install with: uv sync --extra ml"
        ) from exc
    return SentenceTransformerEncoder(SentenceTransformer(model_name))


def load_resume_text(path: str | Path) -> str:
    document = Document(str(path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    if not text:
        raise ValueError(f"resume is empty: {path}")
    return text


def fingerprint_file(path: str | Path) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def resume_fingerprints(resumes: Sequence[ResumeSpec]) -> dict[str, str]:
    return {resume.id: fingerprint_file(resume.path) for resume in resumes}


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def match_percent(left: Sequence[float], right: Sequence[float]) -> float:
    return round(max(0.0, float(cosine_similarity(left, right))) * 100.0, 1)


def score_descriptions(
    resume_texts: dict[str, str],
    descriptions: dict[str, str],
    encoder: Encoder,
) -> dict[str, dict[str, float]]:
    """Map position id -> {resume id: percent}."""
    scores: dict[str, dict[str, float]] = {}
    empty_ids = [pid for pid, description in descriptions.items() if not description.strip()]
    nonempty = {pid: text for pid, text in descriptions.items() if text.strip()}
    for pid in empty_ids:
        scores[pid] = {resume_id: 0.0 for resume_id in resume_texts}
    if not resume_texts:
        return {pid: {} for pid in descriptions}
    if not nonempty:
        return scores
    resume_ids = list(resume_texts)
    resume_vectors = list(encoder.encode([resume_texts[rid] for rid in resume_ids]))
    position_ids = list(nonempty)
    job_vectors = list(encoder.encode([nonempty[pid] for pid in position_ids]))
    for pid, job_vec in zip(position_ids, job_vectors, strict=True):
        scores[pid] = {
            rid: match_percent(rvec, job_vec)
            for rid, rvec in zip(resume_ids, resume_vectors, strict=True)
        }
    return scores
