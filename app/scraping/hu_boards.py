"""Hungarian student-job boards and student cooperatives (iskolaszövetkezetek).

Everything these boards list is already a student job or internship, so the
title-keyword filter is NOT applied here. Instead each board is narrowed to
listings an English speaker can do (English-language category, English search,
or language requirements). The global location filter still applies.

Each board was checked against its robots.txt; the paths used here are allowed.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import re
import time
from collections.abc import Callable

import httpx
from bs4 import BeautifulSoup

from app.config import Settings

from . import register
from .ats import _matches_keywords
from .base import RawJob, Source

logger = logging.getLogger(__name__)

TIMEOUT = 30
DELAY = 1.0  # between requests to the same board
MAX_PAGES = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (job-tracker; personal use)"}
_ENGLISH_RE = re.compile(r"\b(angol|english)\b", re.IGNORECASE)
_EN_WORDS = frozenset("the and you with of to for your in we will are our be".split())
_HU_WORDS = frozenset(
    "és a az hogy vagy nem egy van lesz valamint esetén szükséges feladatok".split()
)


def _written_in_english(html: str) -> bool:
    """Heuristic: an ad written in English is one the employer expects English speakers to read.

    Args:
        html: Ad body (HTML or plain text).

    Returns:
        True if English function words outnumber Hungarian ones.
    """
    words = re.findall(r"[a-záéíóöőúüű]+", re.sub(r"<[^>]+>", " ", html or "").lower())
    return sum(w in _EN_WORDS for w in words) > sum(w in _HU_WORDS for w in words)


def _get(url: str, **kwargs: object) -> httpx.Response:
    resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True, **kwargs)
    resp.raise_for_status()
    return resp


def _text(node: object) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""  # type: ignore[union-attr]


# --- Zyntern (public JSON API) -----------------------------------------------

ZYNTERN_API = "https://zyntern.com/api/jobs"
ZYNTERN_BUDAPEST = "Magyarország;HU;;Budapest;;;47.497912;19.040235;30;"
ZYNTERN_ENGLISH = 160
ZYNTERN_HUNGARIAN = 215
ZYNTERN_TYPES = {1: "Gyakornok", 3: "Diákmunka"}  # 2 = fresh graduate, 7 = junior (full-time)


def _zyntern_needs_native_hungarian(job: dict) -> bool:
    return any(
        lang.get("language_id") == ZYNTERN_HUNGARIAN and lang.get("language_level", 0) >= 100
        for lang in job.get("languages", [])
    )


def fetch_zyntern(settings: Settings) -> list[RawJob]:
    jobs: list[RawJob] = []
    for page in range(1, MAX_PAGES + 1):
        data = _get(
            ZYNTERN_API,
            params={
                "page": page,
                "limit": 50,
                "location": ZYNTERN_BUDAPEST,
                "languages": ZYNTERN_ENGLISH,
            },
        ).json()
        for job in data.get("data", []):
            type_id = (job.get("job_type") or {}).get("id")
            if type_id not in ZYNTERN_TYPES:
                continue
            if settings.hu_boards.skip_native_hungarian and _zyntern_needs_native_hungarian(job):
                continue
            langs = ", ".join(
                f"{lang.get('name')} ({lang.get('level_name')})"
                for lang in job.get("languages", [])
            )
            publishes = job.get("publishes") or [{}]
            jobs.append(
                RawJob(
                    source="board:zyntern",
                    external_id=str(job.get("id", "")),
                    title=job.get("title", ""),
                    company=(job.get("company") or {}).get("name", ""),
                    location=job.get("location", ""),
                    url=job.get("url", ""),
                    published=(publishes[0].get("start_at") or "")[:10],
                    job_type=ZYNTERN_TYPES[type_id],
                    tags=langs,
                    remote=bool(job.get("remote_work_possible")),
                )
            )
        if page >= data.get("meta", {}).get("last_page", 1):
            break
        time.sleep(DELAY)
    return jobs


# --- Mind-Diák (humancentrum JSON API, anonymous guest token) ----------------

MINDDIAK_API = "https://api.humancentrum.hu/"
MINDDIAK_SITE_TYPE = 20


def fetch_minddiak(settings: Settings) -> list[RawJob]:
    headers = {**HEADERS, "Origin": "https://minddiak.hu"}
    with httpx.Client(headers=headers, timeout=TIMEOUT) as client:
        guest = client.post(MINDDIAK_API + "guest", json={"params": {}})
        guest.raise_for_status()
        token = guest.json()["token"]
        time.sleep(DELAY)
        where = {"type": MINDDIAK_SITE_TYPE, "date": dt.date.today().strftime("%Y-%m-%d 00:00:00")}
        resp = client.get(
            MINDDIAK_API + "positions",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "where": json.dumps(where),
                "order": json.dumps(["id DESC"]),
                "offset": 0,
                "limit": 500,
                "include": json.dumps([{"relation": "positionMd"}]),
            },
        )
        resp.raise_for_status()

    jobs = []
    for pos in resp.json():
        body = " ".join(str(pos.get(k) or "") for k in ("description", "requirements"))
        if settings.hu_boards.skip_native_hungarian:
            if not _written_in_english(body):
                continue  # Hungarian-language ad -> expects fluent Hungarian
        elif not _ENGLISH_RE.search(f"{pos.get('name', '')} {body}"):
            continue
        md = pos.get("positionMd") or {}
        wage = ""
        if md.get("salary"):
            wage = (
                f"{md['salary']}"
                + (f"-{md['salaryMax']}" if md.get("salaryMax") else "")
                + " Ft/óra"
            )
        jobs.append(
            RawJob(
                source="board:minddiak",
                external_id=str(pos.get("id", "")),
                title=pos.get("name", ""),
                company="Mind-Diák (client undisclosed)",
                location=pos.get("cityText") or "",
                url=f"https://minddiak.hu/diakmunka/x-{pos.get('id', '')}",
                published=(pos.get("createTime") or "")[:10],
                job_type="Diákmunka",
                tags=wage,
                description=pos.get("description"),
            )
        )
    return jobs


# --- MUISZ (English site, server-rendered; already hides Hungarian-only jobs) --

MUISZ_LIST = "https://www.muisz.hu/en/student-works"
MUISZ_BUDAPEST = 10


def fetch_muisz(settings: Settings) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(
            _get(MUISZ_LIST, params={"locations": MUISZ_BUDAPEST, "page": page}).text, "html.parser"
        )
        items = soup.select("app-job-list-item")
        new = 0
        for item in items:
            props = {}
            for row in item.select(".JobInfoRow"):
                key = _text(row.select_one(".JobPropertyTitle")).rstrip(":")
                props[key] = _text(row.select_one(".JobPropertyValue"))
            link = item.select_one("a.link-button")
            job_id = props.get("Job ID", "").lstrip("#") or (link["href"] if link else "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            new += 1
            href = link["href"] if link else ""
            jobs.append(
                RawJob(
                    source="board:muisz",
                    external_id=job_id,
                    title=_text(item.select_one("h6")),
                    company=_text(item.select_one(".CompanyName")) or "MUISZ (client undisclosed)",
                    location=props.get("Location", ""),
                    url=href if href.startswith("http") else f"https://www.muisz.hu{href}",
                    job_type="Diákmunka",
                    tags="; ".join(
                        filter(
                            None,
                            [
                                _text(item.select_one(".WageBox")),
                                props.get("Expected language skills", ""),
                            ],
                        )
                    ),
                )
            )
        if not items or not new:
            break
        time.sleep(DELAY)
    return jobs


# --- MADS (server-rendered; English roles live in the SSC/BSC category) ------

MADS_PAGES = (
    "https://mads.hu/munka-kategoriak/diakmunka/ssc-bsc",
    "https://mads.hu/munkak/diak?search=english",
)


def _parse_mads(html: str) -> list[RawJob]:
    jobs = []
    for card in BeautifulSoup(html, "html.parser").select("div.card"):
        link = card.select_one("h3 a[href*='/munkak/']")
        if not link:
            continue
        href = link["href"]
        m = re.search(r"-(\d+)/?$", href)
        location = next(
            (_text(t) for t in card.select("a.tag-blue") if "/diakmunka/" in t.get("href", "")), ""
        )
        title = _text(link)
        # MADS puts the employer at the end of the title: "... Intern - Eaton"
        suffix = re.search(r"\s[-–]\s*([^-–]+)$", title)
        jobs.append(
            RawJob(
                source="board:mads",
                external_id=m.group(1) if m else href,
                title=title,
                company=suffix.group(1).strip() if suffix else "MADS (client undisclosed)",
                location=location,
                url=href if href.startswith("http") else f"https://mads.hu{href}",
                job_type="Diákmunka",
                tags=_text(card.select_one(".work-price")),
            )
        )
    return jobs


def fetch_mads(settings: Settings) -> list[RawJob]:
    jobs: dict[str, RawJob] = {}
    for base in MADS_PAGES:
        for page in range(1, MAX_PAGES + 1):
            sep = "&" if "?" in base else "?"
            try:
                html = _get(f"{base}{sep}page={page}").text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:  # MADS 404s past the last page
                    break
                raise
            batch = _parse_mads(html)
            fresh = [j for j in batch if j.external_id not in jobs]
            for job in fresh:
                jobs[job.external_id] = job
            time.sleep(DELAY)
            if not fresh:
                break
    return list(jobs.values())


# --- Schönherz (first page per listing only; "load more" is robots-disallowed) --

SCHONHERZ_PAGES = (
    "https://schonherz.hu/diakmunkak/budapest/jobs-for-foreign-students-",
    "https://schonherz.hu/diakmunkak/budapest/osszes/" + base64.b64encode(b"english").decode(),
)


def fetch_schonherz(settings: Settings) -> list[RawJob]:
    jobs: dict[str, RawJob] = {}
    for url in SCHONHERZ_PAGES:
        soup = BeautifulSoup(_get(url).text, "html.parser")
        for card in soup.select("#ads .ad-list > div.col-md-8"):
            link = card.select_one(".text h4 a")
            if not link:
                continue
            href = link["href"]
            m = re.search(r"/(\d+)-[^/]*/?$", href)
            job_id = m.group(1) if m else href
            jobs.setdefault(
                job_id,
                RawJob(
                    source="board:schonherz",
                    external_id=job_id,
                    title=_text(link),
                    company="Schönherz (client undisclosed)",
                    location="Budapest (Schönherz Budapest office listing)",
                    url=href if href.startswith("http") else f"https://schonherz.hu{href}",
                    job_type="Diákmunka",
                    tags=_text(card.select_one(".sdcard-text h5")),
                ),
            )
        time.sleep(DELAY)
    return list(jobs.values())


# --- Profession.hu (disabled by default: check their terms of use first) -----
# Filter path: page, location 23 = Budapest, language 67 = English,
# employment type 7 = internship / 10 = student job. /en/ is robots-disallowed.

PROFESSION_URL = (
    "https://www.profession.hu/allasok/budapest/"
    "{page},0,23,0,0,0,67,0,0,0,0,0,0,{etype},0,0,0,0,0,0,0,0,0,0,0,0,0,1"
)
PROFESSION_TYPES = {7: "Gyakornok", 10: "Diákmunka"}


def _parse_profession(html: str, job_type: str) -> list[RawJob]:
    jobs = []
    for li in BeautifulSoup(html, "html.parser").select("li.advertisement-result-list-item"):
        if li.get("data-link", "").endswith("/sponsored"):
            continue  # paid ads ignore the filters
        job_id = li.get("data-prof-id", "")
        link = li.select_one("h2 a")
        if not job_id or not link:
            continue
        jobs.append(
            RawJob(
                source="board:profession",
                external_id=job_id,
                title=li.get("data-item-name") or _text(link),
                company=li.get("data-item-brand", ""),
                location=_text(li.select_one(f"#detailed-job-card-{job_id}-details-location")),
                url=link["href"].split("?")[0],
                job_type=job_type,
                tags=_text(li.select_one(f"#detailed-job-card-{job_id}-details-salary")),
            )
        )
    return jobs


def fetch_profession(settings: Settings) -> list[RawJob]:
    jobs: dict[str, RawJob] = {}
    for etype, label in PROFESSION_TYPES.items():
        for page in range(1, MAX_PAGES + 1):
            batch = _parse_profession(
                _get(PROFESSION_URL.format(page=page, etype=etype)).text, label
            )
            fresh = [j for j in batch if j.external_id not in jobs]
            for job in fresh:
                # Highlighted ads ignore the type filter; keep only real student/intern titles.
                if _matches_keywords(job.title, settings.keywords):
                    jobs[job.external_id] = job
            time.sleep(DELAY)
            if not fresh:
                break
    return list(jobs.values())


BOARDS: dict[str, Callable[[Settings], list[RawJob]]] = {
    "zyntern": fetch_zyntern,
    "minddiak": fetch_minddiak,
    "muisz": fetch_muisz,
    "mads": fetch_mads,
    "schonherz": fetch_schonherz,
    "profession": fetch_profession,
}


@register("hu_boards")
class HuBoardsSource(Source):
    name = "hu_boards"

    def fetch(self, settings: Settings) -> list[RawJob]:
        jobs: list[RawJob] = []
        for name, fetcher in BOARDS.items():
            if not getattr(settings.hu_boards, name, False):
                continue
            try:
                batch = fetcher(settings)
                logger.info("hu_boards %s: %d jobs", name, len(batch))
                jobs.extend(batch)
            except Exception:
                logger.exception("hu_boards %s failed", name)
        return jobs
