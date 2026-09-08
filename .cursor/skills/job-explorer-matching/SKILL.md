---
name: job-explorer-matching
description: >-
  Local sentence-transformers matching of DOCX resumes to job descriptions
  for job-explorer. Use when changing resume loading, embeddings, match
  percent, or matching tests.
---

# Resume–job matching

Local only. Default model: `sentence-transformers/all-MiniLM-L6-v2`
(override with `config.json` `"matching.model"`).

## Resumes

`config.json`:

```json
"resumes": [
  { "id": "primary", "path": "resumes/primary.docx" }
]
```

- Load with `python-docx`: concatenate paragraph text with newlines.
- Skip empty files with a hard error.
- Paths are relative to `config.json`'s directory unless absolute.
- Do not commit real resumes; tests use tiny fixture `.docx` files.
- Fingerprint: `sha256:` + hex digest of **file bytes** (not extracted text).
  Compared to newest-email `resume_fingerprints` from the last three reports. Any add/remove/byte change
  means resumes are not old → re-fetch details for previous positions too.

## Scoring

```python
score = round(max(0.0, float(cosine_similarity(r_vec, j_vec))) * 100.0, 1)
```

- Encode resumes once per run; encode each unique job description once.
- Normalize embeddings before cosine (`util.cos_sim` is fine).
- Clamp negative cosine to 0%.
- Multi-resume: store all scores; sort positions by `max(scores)`.

## Runtime

- Persist a snapshot under `{config_dir}/.models/<slug>` (hub id with `/`
  replaced by `--`). Override with `matching.cache_dir` (default `.models`).
- Ready when `modules.json` exists: load that folder with
  `SentenceTransformer(path, local_files_only=True)` — no huggingface.co.
- Otherwise try the Hugging Face hub cache (`local_files_only=True`), else
  download once, then `model.save()` into the snapshot dir.
- Gitignore `.models/`. CI injects a fake encoder; pytest must not download.

## Tests

- Unit: inject a fake encoder that returns known vectors; assert percents.
- Snapshot: if `modules.json` exists, `build_encoder` loads that folder only;
  otherwise it downloads once, `save()`s, and reuses the snapshot next call.
- DOCX fixture: known paragraph text extracted.
- Empty description → 0.0, no exception.
- Ordering: higher cosine sorts first in the report input list.
