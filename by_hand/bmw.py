import asyncio
import json
from datetime import datetime
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_URL = "https://www.bmwgroup.jobs"

ENDPOINT = (
    "https://www.bmwgroup.jobs/de/en/"
    "_jcr_content/main/layoutcontainer_5337/"
    "jobfinder30.jobfinder_table.content.html"
)

OUTPUT_FILE = "bmw_jobs.json"

FILTER_SEARCH = "location_DE,jobType_INTERNSHIP"

FIRST_BLOCK_COUNT = 15
MAX_BLOCK_COUNT = 2000


def build_url(row_index: int, block_count: int) -> str:
    params = {
        "filterSearch": FILTER_SEARCH,
        "rowIndex": row_index,
        "blockCount": block_count,
    }
    return f"{ENDPOINT}?{urlencode(params)}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def parse_posting_date(value: str) -> str:
    value = clean_text(value)

    if not value:
        return ""

    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return value


def parse_jobs_and_total(html: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one(".grp-jobfinder__table")
    total = None

    if table and table.get("data-counter"):
        try:
            total = int(table["data-counter"])
        except ValueError:
            total = None

    jobs = []
    seen_ids = set()

    for wrapper in soup.select(".grp-jobfinder__wrapper[data-job-id]"):
        job_id = clean_text(wrapper.get("data-job-id"))

        link = wrapper.select_one("a.grp-jobfinder__link-jobdescription[href]")
        ref = wrapper.select_one(".grp-jobfinder-cell-refno")

        if not link or not ref or not job_id:
            continue

        if job_id in seen_ids:
            continue

        seen_ids.add(job_id)

        href = link.get("href", "")

        jobs.append(
            {
                "company": "BMW Group",
                "job_id": job_id,
                "title": clean_text(ref.get("data-job-title")),
                "location": clean_text(ref.get("data-job-location")),
                "legal_entity": clean_text(ref.get("data-job-legal-entity")),
                "job_field": clean_text(ref.get("data-job-field")),
                "job_type": clean_text(ref.get("data-job-type")),
                "posted_on": parse_posting_date(ref.get("data-posting-date", "")),
                "url": urljoin(BASE_URL, href),
            }
        )

    return jobs, total


async def fetch_html(request_context, row_index: int, block_count: int) -> str:
    url = build_url(row_index=row_index, block_count=block_count)

    response = await request_context.get(
        url,
        timeout=120_000,
        headers={
            "accept": "text/html, */*; q=0.01",
            "referer": "https://www.bmwgroup.jobs/de/en/jobfinder.html",
            "x-requested-with": "XMLHttpRequest",
        },
    )

    if not response.ok:
        raise RuntimeError(f"BMW request failed: HTTP {response.status}")

    return await response.text()


async def scrape_bmw(request_context) -> list[dict]:
    print("Fetching first BMW page...")

    first_html = await fetch_html(
        request_context=request_context,
        row_index=0,
        block_count=FIRST_BLOCK_COUNT,
    )

    first_jobs, total = parse_jobs_and_total(first_html)

    if total is None:
        print("Could not detect total count; saving first page only.")
        return first_jobs

    print(f"BMW reports {total} matching jobs")

    block_count = min(total, MAX_BLOCK_COUNT)

    print(f"Fetching all BMW jobs with blockCount={block_count}...")

    full_html = await fetch_html(
        request_context=request_context,
        row_index=0,
        block_count=block_count,
    )

    jobs, _ = parse_jobs_and_total(full_html)

    if len(jobs) < total:
        print(f"Warning: expected {total}, parsed {len(jobs)}")

    return jobs


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
            jobs = await scrape_bmw(request_context)
        finally:
            await request_context.dispose()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
