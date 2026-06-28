from __future__ import annotations

import logging
import time

import httpx

from app.config import Settings

from . import register
from .base import RawJob, Source

logger = logging.getLogger(__name__)

BA_ENDPOINT = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
BA_API_KEY = "jobboerse-jobsuche"
MAX_PAGES = 25
PAGE_SIZE = 100
SLEEP_BETWEEN = 0.4

ANGEBOTSART_MAP = {
    "praktikum": "34",
    "arbeit": "1",
}


@register("arbeitsagentur")
class ArbeitsagenturSource(Source):
    name = "arbeitsagentur"

    def fetch(self, settings: Settings) -> list[RawJob]:
        results: list[RawJob] = []
        seen_refnrs: set[str] = set()

        for keyword in settings.keywords:
            try:
                jobs = self._fetch_keyword(keyword, settings)
                for job in jobs:
                    if job.external_id not in seen_refnrs:
                        seen_refnrs.add(job.external_id)
                        results.append(job)
            except Exception:
                logger.exception("arbeitsagentur: error fetching keyword %r", keyword)

        return results

    def _fetch_keyword(self, keyword: str, settings: Settings) -> list[RawJob]:
        jobs: list[RawJob] = []
        headers = {"X-API-Key": BA_API_KEY}

        for page in range(1, MAX_PAGES + 1):
            params: dict[str, str | int] = {
                "was": keyword,
                "page": page,
                "size": PAGE_SIZE,
                "veroeffentlichtseit": settings.published_within_days,
                "pav": "false",
            }
            if settings.location:
                params["wo"] = settings.location
                params["umkreis"] = settings.radius_km

            try:
                resp = httpx.get(BA_ENDPOINT, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("arbeitsagentur: request failed page=%d keyword=%r — %s", page, keyword, exc)
                break

            data = resp.json()
            items = data.get("stellenangebote", [])
            if not items:
                break

            for item in items:
                jobs.append(self._parse_item(item))

            if len(items) < PAGE_SIZE:
                break

            time.sleep(SLEEP_BETWEEN)

        return jobs

    def _parse_item(self, item: dict) -> RawJob:
        refnr = item.get("refnr", "")
        arbeitsort = item.get("arbeitsort", {})
        ort = arbeitsort.get("ort", "")
        region = arbeitsort.get("region", "")
        location = f"{ort}, {region}" if region else ort

        url = item.get("externeUrl") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

        return RawJob(
            source=self.name,
            external_id=refnr,
            title=item.get("titel", ""),
            company=item.get("arbeitgeber", ""),
            location=location,
            url=url,
            published=item.get("aktuelleVeroeffentlichungsdatum", ""),
        )
