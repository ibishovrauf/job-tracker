"""Enterprise ATS providers that need a host plus provider-specific params.

Each fetcher takes (company, settings) and returns every posting the board
yields for the configured location; keyword and location filtering happen
downstream like for every other ATS provider.
"""

from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from app.config import ATSCompany, Settings

from .base import RawJob

logger = logging.getLogger(__name__)

TIMEOUT = 15
BROWSER_UA = {"User-Agent": "Mozilla/5.0"}  # some career sites 403 the default httpx UA
MAX_PAGES = 20  # hard stop so a misconfigured filter can't page through a global board


def _require(company: ATSCompany, *keys: str) -> bool:
    """Log and return False if host or any required param is missing."""
    missing = [k for k in keys if not company.params.get(k)]
    if not company.host:
        missing.insert(0, "host")
    if missing:
        logger.error(
            "%s/%s missing config: %s", company.provider, company.token, ", ".join(missing)
        )
        return False
    return True


# --- Oracle Recruiting Cloud (Candidate Experience) --------------------------
# Config: host="hdjq.fa.us2.oraclecloud.com", site="CX_1", params.location_id="300000000228771"


def _parse_oracle(data: dict, company: ATSCompany) -> tuple[list[RawJob], int]:
    items = data.get("items") or [{}]
    block = items[0]
    jobs = []
    for req in block.get("requisitionList", []):
        locations = [req.get("PrimaryLocation", "")]
        locations += [loc.get("Name", "") for loc in req.get("secondaryLocations", [])]
        site_url = f"https://{company.host}/hcmUI/CandidateExperience/en/sites/{company.site}"
        jobs.append(
            RawJob(
                source=f"ats:oracle:{company.token}",
                external_id=str(req.get("Id", "")),
                title=req.get("Title", ""),
                company=company.name or company.token,
                location="; ".join(loc for loc in locations if loc),
                url=f"{site_url}/job/{req.get('Id', '')}",
                published=(req.get("PostedDate") or "")[:10],
            )
        )
    return jobs, int(block.get("TotalJobsCount", 0))


def fetch_oracle(company: ATSCompany, settings: Settings) -> list[RawJob]:
    """Page through an Oracle CE site filtered to one location id."""
    if not _require(company, "location_id") or not company.site:
        return []
    url = f"https://{company.host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    jobs: list[RawJob] = []
    page_size = 25
    for page in range(MAX_PAGES):
        finder = (
            f"findReqs;siteNumber={company.site},locationId={company.params['location_id']},"
            f"limit={page_size},offset={page * page_size},sortBy=POSTING_DATES_DESC"
        )
        params = {
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": finder,
        }
        resp = httpx.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        batch, total = _parse_oracle(resp.json(), company)
        jobs.extend(batch)
        if not batch or (page + 1) * page_size >= total:
            break
    return jobs


# --- Eightfold PCSX ----------------------------------------------------------
# Config: host="jobs.infineon.com", params={domain: "infineon.com", location: "Hungary"}


def _parse_eightfold(data: dict, company: ATSCompany) -> tuple[list[RawJob], int]:
    block = data.get("data", {})
    jobs = []
    for pos in block.get("positions", []):
        published = ""
        if ts := pos.get("postedTs"):
            published = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
        jobs.append(
            RawJob(
                source=f"ats:eightfold:{company.token}",
                external_id=str(pos.get("displayJobId") or pos.get("id", "")),
                title=pos.get("name", ""),
                company=company.name or company.token,
                location="; ".join(pos.get("standardizedLocations") or pos.get("locations") or []),
                url=f"https://{company.host}{pos.get('positionUrl', '')}",
                published=published,
            )
        )
    return jobs, int(block.get("count", 0))


def fetch_eightfold(company: ATSCompany, settings: Settings) -> list[RawJob]:
    """Page through an Eightfold board filtered by a location string."""
    if not _require(company, "domain", "location"):
        return []
    jobs: list[RawJob] = []
    page_size = 10
    for page in range(MAX_PAGES):
        params = {
            "domain": company.params["domain"],
            "query": "",
            "location": company.params["location"],
            "start": page * page_size,
            "num": page_size,
            "sort_by": "timestamp",
        }
        resp = httpx.get(f"https://{company.host}/api/pcsx/search", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        batch, total = _parse_eightfold(resp.json(), company)
        jobs.extend(batch)
        if not batch or (page + 1) * page_size >= total:
            break
    return jobs


# --- Phenom ------------------------------------------------------------------
# Config: host="www.pgcareers.com",
#   params={lang: "en_global", site_country: "global", page_id: "page16", country: "Hungary"}
# lang / site_country / page_id come from phApp.ddo.siteConfig on any page of the site.


def _parse_phenom(data: dict, company: ATSCompany) -> tuple[list[RawJob], int]:
    block = data.get("refineSearch", {})
    site_country = company.params["site_country"]
    lang = company.params["lang"].split("_")[0]
    jobs = []
    for job in block.get("data", {}).get("jobs", []):
        locations = job.get("multi_location_array") or []
        location = "; ".join(
            loc.get("location", "") if isinstance(loc, dict) else str(loc) for loc in locations
        ) or job.get("location", "")
        jobs.append(
            RawJob(
                source=f"ats:phenom:{company.token}",
                external_id=str(job.get("jobId", "")),
                title=job.get("title", ""),
                company=company.name or company.token,
                location=location,
                url=f"https://{company.host}/{site_country}/{lang}/job/{job.get('jobId', '')}",
                published=(job.get("postedDate") or "")[:10],
            )
        )
    return jobs, int(block.get("totalHits", 0))


def fetch_phenom(company: ATSCompany, settings: Settings) -> list[RawJob]:
    """Page through a Phenom site's refineSearch widget filtered to one country."""
    if not _require(company, "lang", "site_country", "page_id", "country"):
        return []
    jobs: list[RawJob] = []
    page_size = 50
    for page in range(MAX_PAGES):
        body = {
            "lang": company.params["lang"],
            "deviceType": "desktop",
            "country": company.params["site_country"],
            "pageName": "search-results",
            "ddoKey": "refineSearch",
            "sortBy": "Most recent",
            "from": page * page_size,
            "size": page_size,
            "jobs": True,
            "counts": True,
            "all_fields": ["country", "city"],
            "pageId": company.params["page_id"],
            "siteType": "external",
            "keywords": "",
            "global": True,
            "selected_fields": {"country": [company.params["country"]]},
            "locationData": {},
        }
        resp = httpx.post(f"https://{company.host}/widgets", json=body, timeout=TIMEOUT)
        resp.raise_for_status()
        batch, total = _parse_phenom(resp.json(), company)
        jobs.extend(batch)
        if not batch or (page + 1) * page_size >= total:
            break
    return jobs


# --- Oracle Taleo ------------------------------------------------------------
# Config: host="molgroup.taleo.net", site="external",
#   params={portal: "8205100397", location: "2205100397", lang: "hu"}

_TALEO_HEADERS = {
    "Content-Type": "application/json",
    "tz": "GMT+02:00",
    "tzname": "Europe/Budapest",
}


def _taleo_body(location: str, page: int) -> dict:
    return {
        "multilineEnabled": False,
        "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
        "fieldData": {"fields": {"KEYWORD": "", "LOCATION": location}, "valid": True},
        "filterSelectionParam": {
            "searchFilterSelections": [
                {"id": f, "selectedValues": []} for f in ("POSTING_DATE", "LOCATION", "JOB_FIELD")
            ]
        },
        "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
        "pageNo": page,
    }


def _taleo_date(text: str) -> str:
    """Taleo HU dates look like "2026.10.15." -> "2026-10-15"."""
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", text or "")
    return "-".join(m.groups()) if m else ""


def _parse_taleo(data: dict, company: ATSCompany) -> list[RawJob]:
    lang = company.params.get("lang", "en")
    jobs = []
    for req in data.get("requisitionList", []):
        cols = req.get("column") or []
        title = cols[0] if cols else ""
        try:
            location = ", ".join(json.loads(cols[1])) if len(cols) > 1 else ""
        except (TypeError, ValueError):
            location = str(cols[1])
        job_no = req.get("contestNo", "")
        jobs.append(
            RawJob(
                source=f"ats:taleo:{company.token}",
                external_id=str(job_no),
                title=title,
                company=company.name or company.token,
                location=location,
                url=f"https://{company.host}/careersection/{company.site}/jobdetail.ftl?job={job_no}&lang={lang}",
                published=_taleo_date(cols[2]) if len(cols) > 2 else "",
            )
        )
    return jobs


def fetch_taleo(company: ATSCompany, settings: Settings) -> list[RawJob]:
    """Page through a Taleo career section; pages can come back short, so stop on empty."""
    if not _require(company, "portal", "location") or not company.site:
        return []
    url = f"https://{company.host}/careersection/rest/jobboard/searchjobs"
    params = {"lang": company.params.get("lang", "en"), "portal": company.params["portal"]}
    seen: dict[str, RawJob] = {}
    for page in range(1, MAX_PAGES + 1):
        resp = httpx.post(
            url,
            params=params,
            headers=_TALEO_HEADERS,
            json=_taleo_body(company.params["location"], page),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        batch = _parse_taleo(resp.json(), company)
        if not batch:
            break
        for job in batch:
            seen.setdefault(job.external_id, job)
    return list(seen.values())


# --- karrierportal.hu (Nexum) ------------------------------------------------
# Config: token = tenant subdomain, e.g. {provider: karrierportal, token: mvm}


def _parse_karrierportal(data: dict, company: ATSCompany) -> list[RawJob]:
    base = f"https://{company.token}.karrierportal.hu"
    jobs = []
    for row in data.get("rows", []):
        soup = BeautifulSoup(row.get("row", ""), "html.parser")
        title = soup.select_one("a.job_list_title")
        place = soup.select_one(".job_list_place")
        jobs.append(
            RawJob(
                source=f"ats:karrierportal:{company.token}",
                external_id=str(row.get("id", "")),
                title=title.get_text(strip=True) if title else "",
                company=company.name or company.token,
                location=place.get_text(" ", strip=True).replace("Helyszín:", "").strip()
                if place
                else "",
                url=base + row.get("url", ""),
            )
        )
    return jobs


KARRIERPORTAL_COUNTIES = ("Budapest", "Pest megye")


def _karrierportal_query(company: ATSCompany, query: str) -> dict:
    resp = httpx.post(
        f"https://{company.token}.karrierportal.hu/jsbq",
        headers={"X-Requested-With": "XMLHttpRequest"},
        data={"init": "0", "q": f"{query}numOfPages=500&", "ajax": "1", "routeQuery": ""},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_karrierportal(company: ATSCompany, settings: Settings) -> list[RawJob]:
    """Fetch the whole board in one request (numOfPages is really rows per page).

    Some postings show only a street address ("Szentendrei út 207-209.") with no
    city, so a second request asks which ids sit in Budapest / Pest county and
    tags those with the county name.
    """
    jobs = _parse_karrierportal(_karrierportal_query(company, ""), company)
    county_q = "".join(f"workplaces-county[]={c}&" for c in KARRIERPORTAL_COUNTIES)
    by_county = _karrierportal_query(company, county_q)
    local_ids = {str(row.get("id", "")) for row in by_county.get("rows", [])}
    for job in jobs:
        if job.external_id in local_ids and not any(
            c in job.location for c in KARRIERPORTAL_COUNTIES
        ):
            job.location = f"{job.location} ({'/'.join(KARRIERPORTAL_COUNTIES)})".strip()
    return jobs


# --- hrfelho.hu --------------------------------------------------------------
# Config: token = tenant subdomain, e.g. {provider: hrfelho, token: roust}


def _parse_hrfelho(html: str, company: ATSCompany) -> list[RawJob]:
    base = f"https://{company.token}.hrfelho.hu"
    jobs = []
    for tr in BeautifulSoup(html, "html.parser").select("#job-list table tbody tr"):
        link = tr.select_one("a.viewjob")
        title = tr.select_one(".job-title")
        if not link or not title:
            continue
        m = re.search(r"/allasajanlat/(\d+)/", link.get("href", ""))
        loc = tr.select_one('td[data-label="Munkavégzés helye"]')
        jobs.append(
            RawJob(
                source=f"ats:hrfelho:{company.token}",
                external_id=m.group(1) if m else link["href"],
                title=title.get_text(strip=True),
                company=company.name or company.token,
                location=loc.get_text(" ", strip=True) if loc else "",
                url=base + link["href"],
            )
        )
    return jobs


def fetch_hrfelho(company: ATSCompany, settings: Settings) -> list[RawJob]:
    """The full list is on the tenant's home page."""
    resp = httpx.get(f"https://{company.token}.hrfelho.hu/", timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return _parse_hrfelho(resp.text, company)


# --- Veolia Hungary (karrier.veolia.hu, custom site) -------------------------
# Config: {provider: veolia_hu, token: veolia, name: Veolia Hungary}

VEOLIA_BASE = "https://karrier.veolia.hu"


def _parse_veolia(html: str, company: ATSCompany) -> tuple[list[RawJob], int]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#cardContent")
    total_pages = int(content.get("totalpages", 1)) if content else 1
    jobs = []
    for card in soup.select(".position-card"):
        link = card.select_one("a.position-card__header-position")
        if not link:
            continue
        loc = card.select_one(".position-card__header-location")
        sub = card.select_one(".position-card__footer-company")
        jobs.append(
            RawJob(
                source=f"ats:veolia_hu:{company.token}",
                external_id=link["href"].rstrip("/").rsplit("/", 1)[-1],
                title=link.get_text(strip=True),
                company=sub.get_text(strip=True) if sub else (company.name or company.token),
                location=loc.get_text(strip=True) if loc else "",
                url=VEOLIA_BASE + link["href"],
            )
        )
    return jobs, total_pages


def fetch_veolia_hu(company: ATSCompany, settings: Settings) -> list[RawJob]:
    jobs: list[RawJob] = []
    total_pages = 1
    page = 1
    while page <= min(total_pages, MAX_PAGES):
        resp = httpx.get(f"{VEOLIA_BASE}/allasok/{page}", timeout=TIMEOUT)
        resp.raise_for_status()
        batch, total_pages = _parse_veolia(resp.text, company)
        jobs.extend(batch)
        page += 1
    return jobs


# --- SAP SuccessFactors career site (Google Base feed) -----------------------
# Config: host="careers.gedeonrichter.com", params={country: "HU"}
#   optional params.path_contains="/Audi/" for multi-brand sites (jobs.volkswagen-group.com)
# The feed lists every job on the site; /services/ (RSS/JSON) is robots-disallowed.

_GBASE = "{http://base.google.com/ns/1.0}"


def _parse_successfactors(xml_bytes: bytes, company: ATSCompany) -> list[RawJob]:
    country = re.escape(company.params.get("country", ""))
    path_filter = company.params.get("path_contains", "")
    jobs = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        location = item.findtext(f"{_GBASE}location") or ""
        link = item.findtext("link") or ""
        if country and not re.search(rf",\s*{country}\b", location):
            continue
        if path_filter and path_filter not in link:
            continue
        title = re.sub(r"\s*\([^)]*\)$", "", item.findtext("title") or "")  # "X (Budapest, HU)"
        # Hungarian postcodes 1000-1299 are Budapest; some sites only give "BU, HU, 1031".
        if (
            re.search(r",\s*HU\b", location)
            and re.search(r"\b1[0-2]\d\d\b", location)
            and "budapest" not in location.lower()
        ):
            location = f"{location} (Budapest)"
        jobs.append(
            RawJob(
                source=f"ats:successfactors:{company.token}",
                external_id=item.findtext(f"{_GBASE}id") or link,
                title=title,
                company=company.name or item.findtext(f"{_GBASE}employer") or company.token,
                location=location,
                url=link,
            )
        )
    return jobs


def fetch_successfactors(company: ATSCompany, settings: Settings) -> list[RawJob]:
    if not company.host:
        logger.error("successfactors/%s missing config: host", company.token)
        return []
    resp = httpx.get(
        f"https://{company.host}/googlebase.xml",
        headers=BROWSER_UA,
        timeout=60,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return _parse_successfactors(resp.content, company)


# --- Avature -----------------------------------------------------------------
# Config: host="jobs.siemens-energy.com",
#   params={path: "en_US/jobs", filters: "29454=964532&29457=102154"}
#   optional params.city_field="schemaField_3_131" (fallback when JSON-LD has no jobLocation)
# Filter field ids are site-specific (read them from the search page URL).
# The list has no location/date, so each hit's JSON-LD JobPosting is fetched.

AVATURE_PAGE = 20
AVATURE_DELAY = 1.0


def _avature_jsonld(html: str) -> dict:
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _avature_location(posting: dict) -> str:
    places = posting.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    parts = []
    for place in places:
        addr = place.get("address", {}) if isinstance(place, dict) else {}
        parts.append(
            ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressCountry")]))
        )
    return "; ".join(p for p in parts if p)


def fetch_avature(company: ATSCompany, settings: Settings) -> list[RawJob]:
    if not _require(company, "path", "filters"):
        return []
    base = f"https://{company.host}/{company.params['path']}"
    links: list[tuple[str, str]] = []
    for page in range(MAX_PAGES):
        query = (
            f"{company.params['filters']}&listFilterMode=1"
            f"&folderRecordsPerPage={AVATURE_PAGE}&folderOffset={page * AVATURE_PAGE}"
        )
        resp = httpx.get(
            f"{base}/Jobs?{query}", headers=BROWSER_UA, timeout=TIMEOUT, follow_redirects=True
        )
        resp.raise_for_status()
        anchors = BeautifulSoup(resp.text, "html.parser").select("a.article__header__focusable")
        links += [(a.get_text(strip=True), a["href"]) for a in anchors if a.get("href")]
        if len(anchors) < AVATURE_PAGE:
            break
        time.sleep(AVATURE_DELAY)

    jobs = []
    for title, url in links:
        time.sleep(AVATURE_DELAY)
        try:
            detail = httpx.get(url, headers=BROWSER_UA, timeout=TIMEOUT, follow_redirects=True)
            detail.raise_for_status()
            html = detail.text
        except httpx.HTTPError:
            html = ""
        posting = _avature_jsonld(html)
        location = _avature_location(posting)
        # Some postings omit jobLocation from JSON-LD; the page's view data still has the city.
        if not location and (field := company.params.get("city_field")):
            m = re.search(rf'"{re.escape(field)}":"([^"]+)"', html)
            location = m.group(1) if m else ""
        jobs.append(
            RawJob(
                source=f"ats:avature:{company.token}",
                external_id=url.rstrip("/").rsplit("/", 1)[-1],
                title=title,
                company=company.name or company.token,
                location=location,
                url=url,
                published=posting.get("datePosted", ""),
            )
        )
    return jobs


# --- Cornerstone OnDemand (csod.com) -----------------------------------------
# Config: token = corp slug, e.g. {provider: csod, token: henkel, params: {country: hu}}
# The career site page embeds an anonymous bearer token + API host.

CSOD_CRAWL_DELAY = 10  # robots.txt Crawl-delay


def _parse_csod(data: dict, company: ATSCompany) -> list[RawJob]:
    jobs = []
    for req in data.get("data", {}).get("requisitions", []):
        rid = req.get("requisitionId", "")
        locations = [
            ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
            for loc in req.get("locations", [])
        ]
        published = ""
        if m := re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", req.get("postingEffectiveDate") or ""):
            published = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        jobs.append(
            RawJob(
                source=f"ats:csod:{company.token}",
                external_id=str(rid),
                title=req.get("displayJobTitle", ""),
                company=company.name or company.token,
                location="; ".join(loc for loc in locations if loc),
                url=f"https://{company.token}.csod.com/ux/ats/careersite/1/home/requisition/{rid}?c={company.token}",
                published=published,
            )
        )
    return jobs


def fetch_csod(company: ATSCompany, settings: Settings) -> list[RawJob]:
    home = httpx.get(
        f"https://{company.token}.csod.com/ux/ats/careersite/1/home",
        params={"c": company.token, "lang": "en-US"},
        headers=BROWSER_UA,
        timeout=TIMEOUT,
        follow_redirects=True,
    )
    home.raise_for_status()
    token = re.search(r'"token":"([^"]+)"', home.text)
    cloud = re.search(r'"cloud":"([^"]+)"', home.text)
    if not token or not cloud:
        logger.warning("csod/%s: no search token on career page", company.token)
        return []
    body = {
        "careerSiteId": 1,
        "careerSitePageId": 1,
        "pageNumber": 1,
        "pageSize": 100,
        "cultureId": 1,
        "searchText": "",
        "cultureName": "en-US",
        "states": [],
        "countryCodes": [company.params["country"]] if company.params.get("country") else [],
        "cities": [],
        "placeID": "",
        "radius": None,
        "postingsWithinDays": None,
        "customFieldCheckboxKeys": [],
        "customFieldDropdowns": [],
        "customFieldRadios": [],
    }
    time.sleep(CSOD_CRAWL_DELAY)
    resp = httpx.post(
        f"{cloud.group(1)}rec-job-search/external/jobs",
        json=body,
        headers={"Authorization": f"Bearer {token.group(1)}", **BROWSER_UA},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_csod(resp.json(), company)


EXTRA_FETCHERS: dict[str, Callable[[ATSCompany, Settings], list[RawJob]]] = {
    "oracle": fetch_oracle,
    "eightfold": fetch_eightfold,
    "phenom": fetch_phenom,
    "taleo": fetch_taleo,
    "karrierportal": fetch_karrierportal,
    "hrfelho": fetch_hrfelho,
    "veolia_hu": fetch_veolia_hu,
    "successfactors": fetch_successfactors,
    "avature": fetch_avature,
    "csod": fetch_csod,
}
