from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import Settings

from . import register
from .base import RawJob, Source

logger = logging.getLogger(__name__)

ENDPOINT = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 10
SLEEP_BETWEEN = 0.3


@register("arbeitnow")
class ArbeitnowSource(Source):
    name = "arbeitnow"

    def fetch(self, settings: Settings) -> list[RawJob]:
        results: list[RawJob] = []
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=settings.published_within_days)

        for page in range(1, MAX_PAGES + 1):
            try:
                resp = httpx.get(ENDPOINT, params={"page": page}, timeout=30)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("arbeitnow: request failed page=%d — %s", page, exc)
                break

            data = resp.json()
            items = data.get("data", [])
            if not items:
                break

            for item in items:
                raw = self._parse_item(item)
                if not self._matches_keywords(item, settings.keywords):
                    continue
                if not self._within_date(item, cutoff):
                    continue
                if settings.location and settings.location.lower() not in raw.location.lower():
                    continue
                results.append(raw)

            if len(items) < 100:
                break

            time.sleep(SLEEP_BETWEEN)

        return results

    def _parse_item(self, item: dict) -> RawJob:
        slug = item.get("slug", "")
        is_remote = bool(item.get("remote", False))
        tags = item.get("tags", [])
        job_types = item.get("job_types", [])
        created_at = item.get("created_at", 0)

        published = ""
        if created_at:
            published = datetime.fromtimestamp(created_at, tz=timezone.utc).strftime("%Y-%m-%d")

        jt = ", ".join(job_types)
        if is_remote and "remote" not in jt.lower():
            jt = f"{jt}, remote" if jt else "remote"

        return RawJob(
            source=self.name,
            external_id=slug,
            title=item.get("title", ""),
            company=item.get("company_name", ""),
            location=item.get("location", ""),
            url=item.get("url", ""),
            published=published,
            job_type=jt,
            tags=", ".join(tags) if isinstance(tags, list) else str(tags),
            description=item.get("description"),
            remote=is_remote,
        )

    def _matches_keywords(self, item: dict, keywords: list[str]) -> bool:
        import re
        searchable = " ".join([
            item.get("title", ""),
            item.get("description", "") or "",
            " ".join(item.get("tags", [])),
            " ".join(item.get("job_types", [])),
        ]).lower()
        return any(re.search(r'\b' + re.escape(kw.lower()) + r'\b', searchable) for kw in keywords)

    def _within_date(self, item: dict, cutoff: datetime) -> bool:
        created_at = item.get("created_at", 0)
        if not created_at:
            return True
        dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
        return dt >= cutoff
