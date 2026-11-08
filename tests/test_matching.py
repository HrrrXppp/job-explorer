from __future__ import annotations

import sys
import types
from pathlib import Path

from job_explorer.matching import (
    build_encoder,
    fingerprint_file,
    load_resume_text,
    match_percent,
    model_snapshot_dir,
    score_descriptions,
    snapshot_is_present,
)
from tests.conftest import write_docx


class FakeEncoder:
    def __init__(self, mapping: dict[str, list[float]] | None = None) -> None:
        self.mapping = mapping or {}
        self.calls: list[list[str]] = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [self.mapping.get(text, [1.0, 0.0]) for text in texts]


def test_match_percent_known_vectors() -> None:
    assert match_percent([1.0, 0.0], [1.0, 0.0]) == 100.0
    assert match_percent([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert match_percent([1.0, 0.0], [-1.0, 0.0]) == 0.0
    assert match_percent([3.0, 4.0], [3.0, 4.0]) == 100.0


def test_empty_description_is_zero_without_encoding() -> None:
    encoder = FakeEncoder()
    scores = score_descriptions({"r": "resume text"}, {"job": ""}, encoder)
    assert scores["job"]["r"] == 0.0
    assert encoder.calls == []


def test_docx_extract_and_fingerprint(tmpdir) -> None:
    path = write_docx(tmpdir.join("r.docx"), "Hello world")
    assert "Hello world" in load_resume_text(path)
    first = fingerprint_file(path)
    assert first.startswith("sha256:")
    path.write_bytes(path.read_bytes() + b" ")
    assert fingerprint_file(path) != first


def test_ordering_higher_cosine_first() -> None:
    encoder = FakeEncoder(
        {
            "resume": [1.0, 0.0],
            "close": [0.9, 0.1],
            "far": [0.0, 1.0],
        }
    )
    scores = score_descriptions(
        {"r": "resume"},
        {"a": "close", "b": "far"},
        encoder,
    )
    assert scores["a"]["r"] > scores["b"]["r"]


def test_model_snapshot_dir_slugs_hub_id(tmp_path: Path) -> None:
    dest = model_snapshot_dir("sentence-transformers/all-MiniLM-L6-v2", tmp_path)
    assert dest == tmp_path / "sentence-transformers--all-MiniLM-L6-v2"
    assert not snapshot_is_present(dest)


def _install_fake_sentence_transformer(monkeypatch, *, inits: list, save_writes_marker: bool = True):
    class FakeST:
        def __init__(self, name, local_files_only=False, **kwargs):
            inits.append((str(name), local_files_only))
            if local_files_only and not Path(name).joinpath("modules.json").is_file():
                raise OSError("not in local cache")

        def save(self, path) -> None:
            dest = Path(path)
            dest.mkdir(parents=True, exist_ok=True)
            if save_writes_marker:
                (dest / "modules.json").write_text("[]")

        def encode(self, texts, normalize_embeddings=False):
            return [[1.0, 0.0] for _ in texts]

    fake_mod = types.ModuleType("sentence_transformers")
    fake_mod.SentenceTransformer = FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)


def test_build_encoder_uses_snapshot_when_present(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "sentence-transformers--all-MiniLM-L6-v2"
    dest.mkdir()
    (dest / "modules.json").write_text("[]")
    inits: list[tuple[str, bool]] = []
    _install_fake_sentence_transformer(monkeypatch, inits=inits)

    encoder = build_encoder("sentence-transformers/all-MiniLM-L6-v2", cache_dir=tmp_path)

    assert inits == [(str(dest), True)]
    assert encoder.encode(["hi"]) == [[1.0, 0.0]]


def test_build_encoder_downloads_once_then_reuses_snapshot(tmp_path: Path, monkeypatch) -> None:
    inits: list[tuple[str, bool]] = []
    _install_fake_sentence_transformer(monkeypatch, inits=inits)
    model = "sentence-transformers/all-MiniLM-L6-v2"
    dest = tmp_path / "sentence-transformers--all-MiniLM-L6-v2"

    build_encoder(model, cache_dir=tmp_path)
    assert inits == [(model, True), (model, False)]
    assert snapshot_is_present(dest)

    inits.clear()
    build_encoder(model, cache_dir=tmp_path)
    assert inits == [(str(dest), True)]
