from __future__ import annotations

import logging
import time

import httpx

from app.config import Settings

from . import register
from .base import RawJob, Source

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.adzuna.com/v1/api/jobs/de/search"
MAX_PAGES = 5
RESULTS_PER_PAGE = 50
SLEEP_BETWEEN = 1.0


@register("adzuna")
class AdzunaSource(Source):
    name = "adzuna"

    def fetch(self, settings: Settings) -> list[RawJob]:
        if not settings.adzuna.app_id or not settings.adzuna.app_key:
            logger.info("Adzuna skipped: no API key configured")
            return []

        results: list[RawJob] = []
        seen_ids: set[str] = set()

        for keyword in settings.keywords:
            try:
                jobs = self._fetch_keyword(keyword, settings)
                for job in jobs:
                    if job.external_id not in seen_ids:
                        seen_ids.add(job.external_id)
                        results.append(job)
            except Exception:
                logger.exception("adzuna: error fetching keyword %r", keyword)

        return results

    def _fetch_keyword(self, keyword: str, settings: Settings) -> list[RawJob]:
        jobs: list[RawJob] = []

        for page in range(1, MAX_PAGES + 1):
            params: dict[str, str | int] = {
                "app_id": settings.adzuna.app_id,
                "app_key": settings.adzuna.app_key,
                "what": keyword,
                "results_per_page": RESULTS_PER_PAGE,
                "max_days_old": settings.published_within_days,
                "content-type": "application/json",
            }
            if settings.location:
                params["where"] = settings.location

            url = f"{ENDPOINT}/{page}"

            try:
                resp = httpx.get(url, params=params, timeout=30)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("adzuna: request failed page=%d keyword=%r — %s", page, keyword, exc)
                break

            data = resp.json()
            items = data.get("results", [])
            if not items:
                break

            for item in items:
                jobs.append(self._parse_item(item))

            if len(items) < RESULTS_PER_PAGE:
                break

            time.sleep(SLEEP_BETWEEN)

        return jobs

    def _parse_item(self, item: dict) -> RawJob:
        company = item.get("company", {}).get("display_name", "")
        location = item.get("location", {}).get("display_name", "")
        contract_time = item.get("contract_time", "")

        return RawJob(
            source=self.name,
            external_id=str(item.get("id", "")),
            title=item.get("title", ""),
            company=company,
            location=location,
            url=item.get("redirect_url", ""),
            published=item.get("created", "")[:10],
            job_type=contract_time,
            description=item.get("description"),
        )
