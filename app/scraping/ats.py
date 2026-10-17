from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import httpx

from app.config import ATSCompany, Settings

from . import register
from .ats_extra import EXTRA_FETCHERS
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
        if country := company.params.get("country"):
            url += f"&country={country}"
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


WORKDAY_PAGE_SIZE = 20  # Workday rejects larger pages
WORKDAY_MAX_PAGES = 5  # per keyword
_MULTI_LOCATION_RE = re.compile(r"^\d+ Locations$", re.IGNORECASE)


def _parse_workday_posted(posted_on: str, today: date | None = None) -> str:
    """Turn Workday's relative "Posted 3 Days Ago" into an ISO date.

    Args:
        posted_on: The postedOn text from Workday ("Posted Today", "Posted 30+ Days Ago", ...).
        today: Reference date; defaults to today (injectable for tests).

    Returns:
        "YYYY-MM-DD", or "" when the text is not recognised.
    """
    today = today or date.today()
    text = posted_on.lower()
    if "today" in text:
        return today.isoformat()
    if "yesterday" in text:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+? days? ago", text)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return ""


def _workday_base(company: ATSCompany) -> str:
    """Return the CXS API base URL, e.g. https://ms.wd5.myworkdayjobs.com/wday/cxs/ms/External."""
    return f"https://{company.host}/wday/cxs/{company.token}/{company.site}"


def _workday_all_locations(company: ATSCompany, external_path: str) -> str:
    """Fetch the full location list for a posting that Workday shows as "N Locations".

    Args:
        company: The Workday company entry.
        external_path: The posting's externalPath (e.g. "/job/Budapest/Intern_R123").

    Returns:
        All locations joined by "; ", or "" if the detail request fails.
    """
    try:
        resp = httpx.get(f"{_workday_base(company)}{external_path}", timeout=ATS_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError:
        return ""
    info = resp.json().get("jobPostingInfo", {})
    locations = [info.get("location", "")] + list(info.get("additionalLocations", []))
    return "; ".join(loc for loc in locations if loc)


def _parse_workday(data: dict, company: ATSCompany) -> list[RawJob]:
    jobs = []
    org_name = company.name or company.token
    for item in data.get("jobPostings", []):
        path = item.get("externalPath", "")
        if not path:
            continue
        bullets = item.get("bulletFields") or []
        location = item.get("locationsText", "")
        if _MULTI_LOCATION_RE.match(location):
            location = _workday_all_locations(company, path) or location
        jobs.append(RawJob(
            source=f"ats:workday:{company.token}",
            external_id=bullets[0] if bullets else path,
            title=item.get("title", ""),
            company=org_name,
            location=location,
            url=f"https://{company.host}/{company.site}{path}",
            published=_parse_workday_posted(item.get("postedOn", "")),
        ))
    return jobs


def _fetch_workday_all(company: ATSCompany, keywords: list[str]) -> list[RawJob]:
    """Search a Workday board once per keyword (boards are too big to list in full).

    Args:
        company: Entry with token=tenant, plus host and site.
        keywords: Search terms; each becomes Workday's searchText.

    Returns:
        Unique postings across all keyword searches.
    """
    if not company.host or not company.site:
        logger.error("Workday company %r needs both 'host' and 'site'", company.token)
        return []

    seen: set[str] = set()
    all_jobs: list[RawJob] = []
    for kw in keywords:
        for page in range(WORKDAY_MAX_PAGES):
            body = {
                "appliedFacets": {},
                "limit": WORKDAY_PAGE_SIZE,
                "offset": page * WORKDAY_PAGE_SIZE,
                "searchText": kw,
            }
            try:
                resp = httpx.post(f"{_workday_base(company)}/jobs", json=body, timeout=ATS_TIMEOUT)
                resp.raise_for_status()
            except httpx.HTTPError:
                break
            data = resp.json()
            for job in _parse_workday(data, company):
                if job.external_id not in seen:
                    seen.add(job.external_id)
                    all_jobs.append(job)
            if (page + 1) * WORKDAY_PAGE_SIZE >= data.get("total", 0):
                break
    return all_jobs


PROVIDERS: dict[str, dict] = {
    # Providers with a "fetcher" handle their own requests and pagination.
    "workday": {"fetcher": lambda c, s: _fetch_workday_all(c, s.keywords)},
    "smartrecruiters": {"fetcher": lambda c, s: _fetch_smartrecruiters_all(c)},
    **{name: {"fetcher": fn} for name, fn in EXTRA_FETCHERS.items()},
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


class UnknownProviderError(ValueError):
    """Raised when config names an ATS provider this tool doesn't support."""


def fetch_company_raw(company: ATSCompany, settings: Settings) -> list[RawJob]:
    """Fetch every posting for one company, before keyword filtering.

    Args:
        company: One entry from ats.companies.
        settings: Loaded settings (some providers search by settings.keywords).

    Returns:
        All postings the board returned.

    Raises:
        UnknownProviderError: If company.provider is not supported.
        httpx.HTTPError: If the board could not be reached.
    """
    provider_info = PROVIDERS.get(company.provider)
    if not provider_info:
        raise UnknownProviderError(
            f"unknown provider {company.provider!r}; supported: {', '.join(sorted(PROVIDERS))}"
        )
    if fetcher := provider_info.get("fetcher"):
        return fetcher(company, settings)

    urls = provider_info.get("urls") or [provider_info["url"]]
    last_error: httpx.HTTPError | None = None
    for candidate_url in urls:
        try:
            resp = httpx.get(
                candidate_url.format(token=company.token), timeout=ATS_TIMEOUT,
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            last_error = exc
            continue
        if provider_info["json"]:
            return provider_info["parser"](resp.json(), company)
        return provider_info["parser"](resp.text, company)
    assert last_error is not None
    raise last_error


def matches_job_keywords(job: RawJob, settings: Settings) -> bool:
    """Apply the configured keyword filter (title-only or title + description)."""
    if settings.match_title_only:
        searchable = job.title
    else:
        searchable = " ".join(filter(None, [job.title, job.description or "", job.job_type, job.tags]))
    return _matches_keywords(searchable, settings.keywords)


@register("ats")
class ATSSource(Source):
    name = "ats"

    def fetch(self, settings: Settings) -> list[RawJob]:
        all_jobs: list[RawJob] = []

        def _fetch_company(company: ATSCompany) -> list[RawJob]:
            try:
                raw_jobs = fetch_company_raw(company, settings)
            except Exception as exc:
                logger.warning("ATS skip %s/%s: %s", company.provider, company.token, exc)
                return []
            matched = [job for job in raw_jobs if matches_job_keywords(job, settings)]
            if matched:
                logger.info(
                    "ATS %s/%s: %d matched of %d",
                    company.provider, company.token, len(matched), len(raw_jobs),
                )
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
