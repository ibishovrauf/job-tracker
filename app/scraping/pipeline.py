from __future__ import annotations

import logging
from datetime import datetime

from sqlmodel import Session, select

from app.config import Settings
from app.db import get_engine
from app.models import Job

from . import REGISTRY, discover
from .base import RawJob
from .dedup import make_dedup_key, make_uid
from .tagger import compute_categories

logger = logging.getLogger(__name__)


def run_pipeline(
    settings: Settings, *, dry_run: bool = False
) -> dict[str, int]:
    discover()
    raw_jobs = _fetch_all(settings)

    fetched = len(raw_jobs)
    new = 0
    dedup_skipped = 0

    # Sources that bypass cross-source dedup (their data is authoritative).
    # Same-source UID dedup still applies — we just don't skip them because
    # another source already has a similar job.
    AUTHORITATIVE_PREFIXES = ("byhand:", "portal:")

    def _is_authoritative(src: str) -> bool:
        return any(src.startswith(p) for p in AUTHORITATIVE_PREFIXES)

    if dry_run:
        engine = get_engine(settings.database_url)
        with Session(engine) as session:
            for raw in raw_jobs:
                uid = make_uid(raw.source, raw.external_id)
                dk = make_dedup_key(raw.company, raw.title, raw.location)
                existing_uid = session.get(Job, uid)
                if existing_uid:
                    continue
                if not _is_authoritative(raw.source):
                    existing_dk = session.exec(
                        select(Job).where(Job.dedup_key == dk)
                    ).first()
                    if existing_dk:
                        dedup_skipped += 1
                        continue
                new += 1
    else:
        engine = get_engine(settings.database_url)
        with Session(engine) as session:
            for raw in raw_jobs:
                uid = make_uid(raw.source, raw.external_id)
                dk = make_dedup_key(raw.company, raw.title, raw.location)

                if session.get(Job, uid):
                    continue

                if not _is_authoritative(raw.source):
                    existing = session.exec(
                        select(Job).where(Job.dedup_key == dk)
                    ).first()
                    if existing:
                        dedup_skipped += 1
                        continue

                job = Job(
                    uid=uid,
                    source=raw.source,
                    external_id=raw.external_id,
                    dedup_key=dk,
                    title=raw.title,
                    company=raw.company,
                    location=raw.location,
                    url=raw.url,
                    published=raw.published or datetime.utcnow().strftime("%Y-%m-%d"),
                    job_type=raw.job_type,
                    tags=raw.tags,
                    description=raw.description,
                    remote=raw.remote,
                    category=compute_categories(raw.title, raw.description),
                    first_seen=datetime.utcnow(),
                )
                session.add(job)
                new += 1

            session.commit()

    return {"fetched": fetched, "new": new, "dedup_skipped": dedup_skipped}


def _fetch_all(settings: Settings) -> list[RawJob]:
    all_jobs: list[RawJob] = []

    for name, source_cls in REGISTRY.items():
        source_enabled = getattr(settings.sources, name, False)
        if not source_enabled:
            logger.info("Source %r disabled, skipping", name)
            continue

        if name == "adzuna" and not (settings.adzuna.app_id and settings.adzuna.app_key):
            logger.info("Adzuna skipped: no API key configured")
            continue

        try:
            source = source_cls()
            jobs = source.fetch(settings)
            logger.info("Source %r: fetched %d jobs", name, len(jobs))
            all_jobs.extend(jobs)
        except Exception:
            logger.exception("Source %r failed", name)

    return all_jobs
