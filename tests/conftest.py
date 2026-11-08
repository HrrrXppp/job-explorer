from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from docx import Document
from pytest import fixture


def write_docx(path, text: str) -> Path:
    dest = Path(str(path))
    document = Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    dest.parent.mkdir(parents=True, exist_ok=True)
    document.save(dest)
    return dest


async def nosleep(_: float) -> None:
    return None


@fixture
def resume_docx(tmpdir) -> Path:
    return write_docx(tmpdir.join("primary.docx"), "Python backend engineer. FastAPI, Postgres.")


@fixture
def write_cli_config(tmpdir) -> Callable[..., Path]:
    def _write(resume: Path, user_agent: str = "Ada (ada@example.com)") -> Path:
        config_path = Path(str(tmpdir.join("config.json")))
        config_path.write_text(
            f"""
{{
  "user_agent": "{user_agent}",
  "resumes": [{{ "id": "primary", "path": "{resume.as_posix()}" }}],
  "email": {{ "to": ["me@example.com"] }},
  "sources": [
    {{
      "id": "example",
      "search_request": {{
        "method": "GET",
        "url": "https://example.com/search"
      }},
      "items": {{
        "kind": "json",
        "list": "$.results",
        "fields": {{ "id": "id", "title": "title", "url": "html_url" }}
      }},
      "detail_request": {{
        "method": "GET",
        "url": "https://example.com/jobs/{{id}}",
        "description": "$.description"
      }}
    }}
  ]
}}
""",
            encoding="utf-8",
        )
        return config_path

    return _write
