import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_URL = "https://jobs.volkswagen-group.com"
BASE_SEARCH_URL = "https://jobs.volkswagen-group.com/Volkswagen/search/"
OUTPUT_FILE = "volkswagen_jobs.json"

CAREER_LEVELS = ["Interns", "Students"]
PAGE_SIZE = 25
MAX_JOBS = 2000
MAX_CONCURRENCY = 5


def build_url(career_level: str, startrow: int = 0) -> str:
    params = {
        "searchby": "location",
        "createNewAlert": "false",
        "q": "",
        "locationsearch": "germany",
        "geolocation": "",
        "optionsFacetsDD_city": "",
        "optionsFacetsDD_facility": "",
        "optionsFacetsDD_department": "",
        "optionsFacetsDD_customfield2": career_level,
        "optionsFacetsDD_shifttype": "",
        "optionsFacetsDD_customfield3": "",
        "startrow": startrow,
    }
    return f"{BASE_SEARCH_URL}?{urlencode(params)}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def parse_date(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass

    return value


def extract_job_id_from_url(url: str) -> str:
    match = re.search(r"/(\d+)/?$", urlparse(url).path)
    return match.group(1) if match else ""


def parse_total_count(soup: BeautifulSoup) -> int | None:
    text = soup.get_text(" ", strip=True)
    match = re.search(r"Results\s+\d+\s*[–-]\s*\d+\s+of\s+(\d+)", text)
    return int(match.group(1)) if match else None


def parse_jobs_and_total(html: str, career_level: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    total = parse_total_count(soup)

    jobs = []
    seen_urls = set()

    for link in soup.select('a[href*="/Volkswagen/job/"]'):
        href = link.get("href", "")
        url = urljoin(BASE_URL, href)

        if url in seen_urls:
            continue

        seen_urls.add(url)

        title = clean_text(link.get_text(" ", strip=True))
        row = link.find_parent("tr")

        cells = [clean_text(td.get_text(" ", strip=True)) for td in row.select("td")] if row else []

        company = ""
        department = ""
        location = ""
        posted_on = ""

        # Typical table columns:
        # title, company, department, location, posting date
        if len(cells) >= 5:
            company = cells[1]
            department = cells[2]
            location = cells[3]
            posted_on = parse_date(cells[4])

        jobs.append(
            {
                "company": company or "Volkswagen AG",
                "job_id": "",
                "url_id": extract_job_id_from_url(url),
                "title": title,
                "location": location,
                "department": department,
                "career_level": career_level,
                "working_model": "",
                "contract_type": "",
                "remote_working": "",
                "posted_on": posted_on,
                "url": url,
            }
        )

    return jobs, total


def parse_detail_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]

    def find_value(label: str) -> str:
        pattern = re.compile(rf"^{re.escape(label)}:\s*(.+)$", re.I)

        for i, line in enumerate(lines):
            match = pattern.match(line)
            if match:
                return clean_text(match.group(1))

            # Handles:
            # Location:
            # Wolfsburg, DE, 38436
            if line.rstrip(":").lower() == label.lower():
                for next_line in lines[i + 1 : i + 4]:
                    value = clean_text(next_line)
                    if value:
                        return value

        return ""

    title_el = soup.select_one("h1")
    title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""

    return {
        "title": title,
        "job_id": find_value("Job ID"),
        "company": find_value("Company"),
        "location": find_value("Location"),
        "department": find_value("Department"),
        "career_level": find_value("Career Level"),
        "working_model": find_value("Working Model"),
        "contract_type": find_value("Contract Type"),
        "remote_working": find_value("Remote Working"),
        "posted_on": parse_date(find_value("Posting Date")),
    }


async def fetch_html(request_context, url: str) -> str:
    response = await request_context.get(
        url,
        timeout=120_000,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": "https://jobs.volkswagen-group.com/Volkswagen/",
        },
    )

    if not response.ok:
        raise RuntimeError(f"Volkswagen request failed: HTTP {response.status} for {url}")

    return await response.text()


async def scrape_category(request_context, career_level: str) -> list[dict]:
    first_html = await fetch_html(request_context, build_url(career_level, 0))
    first_jobs, total = parse_jobs_and_total(first_html, career_level)

    if total is None:
        return first_jobs

    total = min(total, MAX_JOBS)
    jobs = first_jobs

    for startrow in range(PAGE_SIZE, total, PAGE_SIZE):
        html = await fetch_html(request_context, build_url(career_level, startrow))
        page_jobs, _ = parse_jobs_and_total(html, career_level)
        jobs.extend(page_jobs)

    return jobs


async def enrich_job(request_context, semaphore, job: dict) -> dict:
    async with semaphore:
        try:
            html = await fetch_html(request_context, job["url"])
            detail = parse_detail_page(html)

            enriched = {**job}
            for key, value in detail.items():
                if value:
                    enriched[key] = value

            return enriched

        except Exception as exc:
            print(f"Warning: detail fetch failed for {job['url']}: {exc}")
            return job


async def scrape_volkswagen(request_context) -> list[dict]:
    all_jobs = []

    for career_level in CAREER_LEVELS:
        print(f"Fetching Volkswagen {career_level} jobs...")
        jobs = await scrape_category(request_context, career_level)
        all_jobs.extend(jobs)

    deduped = []
    seen = set()

    for job in all_jobs:
        key = job.get("url") or job.get("url_id")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)

    print(f"Parsed {len(deduped)} Volkswagen jobs from listings")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    enriched = await asyncio.gather(
        *[enrich_job(request_context, semaphore, job) for job in deduped]
    )

    return enriched


async def main():
    async with async_playwright() as p:
        request_context = await p.request.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            ),
            extra_http_headers={
                "accept-language": "en-US,en;q=0.9,de;q=0.8",
            },
        )

        try:
            jobs = await scrape_volkswagen(request_context)
        finally:
            await request_context.dispose()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
