from __future__ import annotations

import hashlib
import logging
import math
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from docx import Document

from job_explorer.models import ResumeSpec

logger = logging.getLogger(__name__)

SNAPSHOT_MARKER = "modules.json"


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class SentenceTransformerEncoder:
    def __init__(self, model: object) -> None:
        self._model = model

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]


def model_snapshot_dir(model_name: str, cache_dir: str | Path) -> Path:
    given = Path(model_name)
    if given.exists() and given.is_dir():
        return given
    return Path(cache_dir) / model_name.replace("/", "--")


def snapshot_is_present(path: Path) -> bool:
    return (path / SNAPSHOT_MARKER).is_file()


@contextmanager
def _huggingface_offline() -> Iterator[None]:
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_encoder(model_name: str, cache_dir: str | Path = ".models") -> Encoder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required to match resumes. "
            "Install with: uv sync --extra ml"
        ) from exc

    dest = model_snapshot_dir(model_name, cache_dir)
    if snapshot_is_present(dest):
        logger.info("loading embedding model from %s", dest)
        with _huggingface_offline():
            model = SentenceTransformer(str(dest), local_files_only=True)
        return SentenceTransformerEncoder(model)

    logger.info("downloading embedding model %s (saving to %s)", model_name, dest)
    try:
        with _huggingface_offline():
            model = SentenceTransformer(model_name, local_files_only=True)
    except Exception:
        model = SentenceTransformer(model_name)
    dest.mkdir(parents=True, exist_ok=True)
    model.save(str(dest))
    return SentenceTransformerEncoder(model)


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
