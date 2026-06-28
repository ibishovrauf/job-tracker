from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from app.config import ATSCompany, Settings

from . import register
from .base import RawJob, Source

ATS_TIMEOUT = 8  # seconds — fast timeout; real boards respond in <2s
ATS_WORKERS = 20  # parallel fetches

logger = logging.getLogger(__name__)


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    import re
    lower = text.lower()
    for kw in keywords:
        # Word-boundary match: "Intern" must not match "Internal"
        if re.search(r'\b' + re.escape(kw.lower()) + r'\b', lower):
            return True
    return False


def _parse_greenhouse(data: dict, company: ATSCompany) -> list[RawJob]:
    jobs = []
    org_name = company.name or company.token
    for item in data.get("jobs", []):
        loc = item.get("location", {})
        loc_name = loc.get("name", "") if isinstance(loc, dict) else str(loc)
        jobs.append(RawJob(
            source=f"ats:greenhouse:{company.token}",
            external_id=str(item.get("id", "")),
            title=item.get("title", ""),
            company=org_name,
            location=loc_name,
            url=item.get("absolute_url", ""),
            description=item.get("content"),
        ))
    return jobs


def _parse_lever(data: list, company: ATSCompany) -> list[RawJob]:
    jobs = []
    org_name = company.name or company.token
    for item in data:
        cats = item.get("categories", {})
        loc = cats.get("location", "")
        commitment = cats.get("commitment", "")

        # Lever's createdAt is milliseconds since epoch
        published = ""
        created_at = item.get("createdAt")
        if created_at and isinstance(created_at, (int, float)):
            try:
                from datetime import datetime, timezone
                published = datetime.fromtimestamp(
                    created_at / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d")
            except (OSError, ValueError):
                published = ""

        jobs.append(RawJob(
            source=f"ats:lever:{company.token}",
            external_id=str(item.get("id", "")),
            title=item.get("text", ""),
            company=org_name,
            location=loc,
            url=item.get("hostedUrl", ""),
            job_type=commitment,
            description=item.get("descriptionPlain"),
            published=published,
        ))
    return jobs


def _parse_ashby(data: dict, company: ATSCompany) -> list[RawJob]:
    jobs = []
    org_name = company.name or data.get("name", company.token)
    for item in data.get("jobs", []):
        jobs.append(RawJob(
            source=f"ats:ashby:{company.token}",
            external_id=str(item.get("id", "")),
            title=item.get("title", ""),
            company=org_name,
            location=item.get("location", ""),
            url=item.get("jobUrl", ""),
            job_type=item.get("employmentType", ""),
            published=item.get("publishedDate", ""),
        ))
    return jobs


def _parse_personio(xml_text: str, company: ATSCompany) -> list[RawJob]:
    jobs = []
    org_name = company.name or company.token
    root = ET.fromstring(xml_text)
    for pos in root.iter("position"):
        pid = pos.findtext("id", "")
        title = pos.findtext("name", "")
        office = pos.findtext("office", "")
        emp_type = pos.findtext("employmentType", "")
        category = pos.findtext("recruitingCategory", "")
        jt = ", ".join(filter(None, [emp_type, category]))
        jobs.append(RawJob(
            source=f"ats:personio:{company.token}",
            external_id=pid,
            title=title,
            company=org_name,
            location=office,
            url=f"https://{company.token}.jobs.personio.de/job/{pid}",
            job_type=jt,
        ))
    return jobs


def _parse_smartrecruiters(data: dict, company: ATSCompany) -> list[RawJob]:
    jobs = []
    org_name = company.name or company.token
    for item in data.get("content", []):
        loc = item.get("location", {})
        city = loc.get("city", "")
        country = loc.get("country", "")
        location = f"{city}, {country}" if country else city

        published = ""
        released = item.get("releasedDate", "")
        if released:
            published = released[:10]

        jobs.append(RawJob(
            source=f"ats:smartrecruiters:{company.token}",
            external_id=str(item.get("id", "")),
            title=item.get("name", ""),
            company=org_name,
            location=location,
            url=f"https://jobs.smartrecruiters.com/{company.token}/{item.get('id', '')}",
            published=published,
            job_type=item.get("typeOfEmployment", {}).get("label", "") if isinstance(item.get("typeOfEmployment"), dict) else "",
        ))
    return jobs


def _fetch_smartrecruiters_all(company: ATSCompany) -> list[RawJob]:
    """SmartRecruiters paginates with offset/limit, max 100 per page."""
    all_jobs: list[RawJob] = []
    offset = 0
    limit = 100
    while True:
        url = f"https://api.smartrecruiters.com/v1/companies/{company.token}/postings?limit={limit}&offset={offset}"
        try:
            resp = httpx.get(url, timeout=ATS_TIMEOUT)
            resp.raise_for_status()
        except httpx.HTTPError:
            break
        data = resp.json()
        jobs = _parse_smartrecruiters(data, company)
        all_jobs.extend(jobs)
        total_found = data.get("totalFound", 0)
        offset += limit
        if offset >= total_found:
            break
    return all_jobs


PROVIDERS: dict[str, dict] = {
    "smartrecruiters": {
        "url": "https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100",
        "parser": _parse_smartrecruiters,
        "json": True,
        "paginated": True,
    },
    "greenhouse": {
        "url": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
        "parser": _parse_greenhouse,
        "json": True,
    },
    "lever": {
        "url": "https://api.lever.co/v0/postings/{token}?mode=json",
        "parser": _parse_lever,
        "json": True,
    },
    "ashby": {
        "url": "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true",
        "parser": _parse_ashby,
        "json": True,
    },
    "personio": {
        "urls": [
            "https://{token}.jobs.personio.com/xml",
            "https://{token}.jobs.personio.de/xml",
        ],
        "parser": _parse_personio,
        "json": False,
    },
}


@register("ats")
class ATSSource(Source):
    name = "ats"

    def fetch(self, settings: Settings) -> list[RawJob]:
        all_jobs: list[RawJob] = []

        def _fetch_company(company: ATSCompany) -> list[RawJob]:
            provider_info = PROVIDERS.get(company.provider)
            if not provider_info:
                logger.error("Unknown ATS provider %r for token %r", company.provider, company.token)
                return []

            # SmartRecruiters has its own paginated fetcher
            if provider_info.get("paginated") and company.provider == "smartrecruiters":
                try:
                    raw_jobs = _fetch_smartrecruiters_all(company)
                except Exception:
                    logger.warning("ATS fetch failed: %s/%s", company.provider, company.token)
                    return []
            else:
                urls = provider_info.get("urls") or [provider_info["url"]]
                resp = None
                for candidate_url in urls:
                    u = candidate_url.format(token=company.token)
                    try:
                        resp = httpx.get(u, timeout=ATS_TIMEOUT, follow_redirects=True)
                        resp.raise_for_status()
                        break
                    except httpx.HTTPError:
                        resp = None
                        continue

                if resp is None:
                    logger.warning("ATS skip: %s/%s", company.provider, company.token)
                    return []

                try:
                    if provider_info["json"]:
                        data = resp.json()
                        raw_jobs = provider_info["parser"](data, company)
                    else:
                        raw_jobs = provider_info["parser"](resp.text, company)
                except Exception:
                    logger.warning("ATS parse failed: %s/%s", company.provider, company.token)
                    return []

            matched = []
            for job in raw_jobs:
                searchable = " ".join(filter(None, [job.title, job.description or "", job.job_type, job.tags]))
                if _matches_keywords(searchable, settings.keywords):
                    matched.append(job)

            if matched:
                logger.info("ATS %s/%s: %d matched of %d", company.provider, company.token, len(matched), len(raw_jobs))
            return matched

        with ThreadPoolExecutor(max_workers=ATS_WORKERS) as pool:
            futures = {pool.submit(_fetch_company, c): c for c in settings.ats.companies}
            for future in as_completed(futures):
                try:
                    all_jobs.extend(future.result())
                except Exception:
                    c = futures[future]
                    logger.warning("ATS worker error: %s/%s", c.provider, c.token)

        return all_jobs
