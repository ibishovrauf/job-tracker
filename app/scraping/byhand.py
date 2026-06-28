"""By-hand scraper source.

Reads jobs from the `by_hand/all_jobs.json` file produced by the user's
hand-written scrapers (BMW, Mercedes, SAP, Porsche, VW, Siemens, etc.) and
feeds them into the normal pipeline as `source = "byhand:<scraper_name>"`.

This way the user can run their custom scripts (which know each company's
specific quirks) and see the results in the web dashboard alongside the
API-scraped jobs, but in a dedicated `/byhand` tab.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import Settings

from . import register
from .base import RawJob, Source

logger = logging.getLogger(__name__)

DEFAULT_BYHAND_DIR = "by_hand"
DEFAULT_COMBINED_FILE = "all_jobs.json"


def _normalize_location(raw: dict) -> str:
    """Pick best available location string from various source fields."""
    loc = raw.get("location") or ""
    if loc and loc not in ("2 Locations", "3 Locations", "Multiple Locations"):
        return str(loc).strip()

    # Fall back to city, country
    parts = []
    if raw.get("city"):
        parts.append(str(raw["city"]).strip())
    if raw.get("country"):
        parts.append(str(raw["country"]).strip())
    if parts:
        return ", ".join(parts)

    return str(loc).strip() if loc else ""


def _normalize_published(raw: dict) -> str:
    """Pick the best date field."""
    for key in ("posted_on", "published_on", "start_date", "scraped_on"):
        v = raw.get(key)
        if v and isinstance(v, str):
            # Filter out garbage like "Posted 2 Days Ago"
            if v.startswith("20") and len(v) >= 10:
                return v[:10]
    return raw.get("scraped_on", "")[:10] if raw.get("scraped_on") else ""


def _normalize_job_type(raw: dict) -> str:
    """Combine multiple type fields into a readable string."""
    parts = []
    for key in ("job_type", "employment_type", "contract_type", "career_level",
                "career_status", "schedule"):
        v = raw.get(key)
        if v and isinstance(v, str) and v.strip():
            parts.append(v.strip())
    # Dedupe while preserving order
    seen = set()
    deduped = []
    for p in parts:
        if p.lower() not in seen:
            seen.add(p.lower())
            deduped.append(p)
    return ", ".join(deduped)


@register("byhand")
class ByHandSource(Source):
    name = "byhand"

    def fetch(self, settings: Settings) -> list[RawJob]:
        path = Path(getattr(settings, "byhand_combined_path", None)
                    or f"{DEFAULT_BYHAND_DIR}/{DEFAULT_COMBINED_FILE}")
        if not path.exists():
            logger.warning(
                "By-hand source: file not found at %s — run "
                "`python by_hand/run_all_jobs.py` first.", path,
            )
            return []

        try:
            data = json.loads(path.read_text())
        except Exception as e:
            logger.error("By-hand source: failed to read %s: %s", path, e)
            return []

        if not isinstance(data, list):
            logger.error("By-hand source: expected JSON array, got %s", type(data).__name__)
            return []

        results: list[RawJob] = []
        for raw in data:
            try:
                src_name = raw.get("source", "unknown")
                job_id = raw.get("job_id") or raw.get("url_id") or raw.get("requisition_id") \
                         or raw.get("position_id") or raw.get("url", "")[-32:]
                if not job_id:
                    continue

                title = (raw.get("title") or "").strip()
                if not title or title.lower() in ("skip to content skip to footer",):
                    continue

                company = (raw.get("company") or "").strip()
                if not company:
                    continue

                url = (raw.get("url") or raw.get("apply_url") or "").strip()
                if not url:
                    continue

                results.append(RawJob(
                    source=f"byhand:{src_name}",
                    external_id=str(job_id),
                    title=title,
                    company=company,
                    location=_normalize_location(raw),
                    url=url,
                    published=_normalize_published(raw),
                    job_type=_normalize_job_type(raw),
                    description=raw.get("description") or raw.get("raw_text"),
                ))
            except Exception:
                logger.warning("By-hand source: skipping malformed entry", exc_info=True)

        logger.info("By-hand source: loaded %d jobs from %s", len(results), path)
        return results
