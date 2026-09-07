from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone

import httpx

from job_explorer.config import ConfigError, load_config
from job_explorer.crawler import SleepFn, crawl_all
from job_explorer.gmail_client import GmailClient, GmailPort
from job_explorer.matching import Encoder, build_encoder, load_resume_text, resume_fingerprints, score_descriptions
from job_explorer.models import AppConfig, CachedPosition, CrawledItem, ScoredPosition
from job_explorer.report import build_message, snippet
from job_explorer.state import cached_by_id, skip_detail_ids, split_new_previous

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl job sources, match resumes, email a Gmail report.")
    parser.add_argument("--config", default="config.json", help="Path to config.json (default: ./config.json)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    try:
        config = load_config(args.config)
        asyncio.run(run_explorer(config))
    except (ConfigError, FileNotFoundError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        logger.error("%s", exc)
        return 1
    return 0


async def run_explorer(
    config: AppConfig,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
    gmail: GmailPort | None = None,
    encoder: Encoder | None = None,
    now: Callable[[], datetime] | None = None,
    sleep: SleepFn | None = None,
) -> tuple[list[ScoredPosition], list[ScoredPosition]]:
    environ = env if env is not None else os.environ
    clock = now or (lambda: datetime.now(timezone.utc))
    gmail_client = gmail or GmailClient.from_env(environ)
    previous = gmail_client.fetch_previous_state()
    fingerprints = resume_fingerprints(config.resumes)
    skip_ids = skip_detail_ids(previous, fingerprints)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        headers={"User-Agent": config.user_agent},
        timeout=30.0,
        follow_redirects=False,
    )
    try:
        crawled = await crawl_all(
            http_client,
            config.sources,
            skip_detail_ids=skip_ids,
            sleep=sleep or asyncio.sleep,
        )
    finally:
        if owns_client:
            await http_client.aclose()

    resume_texts = {spec.id: load_resume_text(spec.path) for spec in config.resumes}
    matcher = encoder or build_encoder(config.matching.model)
    cache = cached_by_id(previous)
    scored = score_crawled(crawled, resume_texts, matcher, cache)
    new_rows, previous_rows = split_new_previous(scored, previous.position_ids)

    sender = environ.get("GMAIL_USER") or ""
    recipients = config.email.to or ([sender] if sender else [])
    if not sender or not recipients:
        raise RuntimeError("GMAIL_USER is required to send mail (and email.to if you want other recipients)")
    message = build_message(
        sender=sender,
        to=recipients,
        new_rows=new_rows,
        previous_rows=previous_rows,
        fingerprints=fingerprints,
        when=clock(),
    )
    gmail_client.send_raw(bytes(message))
    logger.info("sent report: %s", message["Subject"])
    return new_rows, previous_rows


def score_crawled(
    crawled: list[CrawledItem],
    resume_texts: dict[str, str],
    encoder: Encoder,
    cache: dict[str, CachedPosition],
) -> list[ScoredPosition]:
    to_match: dict[str, str] = {}
    reused: list[ScoredPosition] = []
    items_by_id = {item.id: item for item in crawled}
    for item in crawled:
        if item.skipped_detail:
            cached = cache.get(item.id)
            if cached is None:
                to_match[item.id] = item.description or ""
                continue
            reused.append(
                ScoredPosition(
                    id=item.id,
                    title=item.title or cached.title,
                    url=item.url or cached.url,
                    source_id=item.source_id or cached.source_id,
                    scores=dict(cached.scores),
                    snippet=None,
                )
            )
            continue
        to_match[item.id] = item.description or ""
    matched_scores = score_descriptions(resume_texts, to_match, encoder) if to_match else {}
    scored: list[ScoredPosition] = list(reused)
    for position_id, scores in matched_scores.items():
        item = items_by_id[position_id]
        scored.append(
            ScoredPosition(
                id=item.id,
                title=item.title,
                url=item.url,
                source_id=item.source_id,
                scores=scores,
                snippet=snippet(item.description),
            )
        )
    return scored


if __name__ == "__main__":
    sys.exit(main())
