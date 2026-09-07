from __future__ import annotations

from job_explorer.matching import fingerprint_file, load_resume_text, match_percent, score_descriptions
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
