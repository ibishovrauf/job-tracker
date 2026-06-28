import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

BASE_URL = "https://jobs.siemens-healthineers.com"

START_URL = (
    "https://jobs.siemens-healthineers.com/en_US/searchjobs/SearchJobs/"
    "?42420=%5B812132%5D"
    "&42420_format=17573"
    "&42424=%5B102154%5D"
    "&42424_format=17577"
    "&listFilterMode=1"
    "&folderSort=postedDate"
    "&folderSortDirection=ASC"
    "&folderRecordsPerPage=6"
)

OUTPUT_FILE = "siemens_healthineers_jobs.json"

PAGE_SIZE = 6
MAX_PAGES = 100
MAX_DETAIL_CONCURRENCY = 4

JOB_ID_RE = re.compile(
    r"/JobDetail/(?:.*?/)?(\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)


def make_page_url(offset: int) -> str:
    return f"{START_URL}&folderOffset={offset}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def parse_date(value: str) -> str:
    value = clean_text(value)

    if not value:
        return ""

    for fmt in (
        "%b %d, %Y",
        "%B %d, %Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass

    return value


def extract_job_id(url: str) -> str:
    match = JOB_ID_RE.search(url)
    return match.group(1) if match else ""


def clean_title(text: str) -> str:
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]

    bad_lines = {
        "learn more",
        "share",
        "apply",
        "bewerben",
        "job details",
        "details",
        "save job",
        "saved job",
        "job speichern",
        "teilen",
    }

    for line in lines:
        lower = line.lower()
        if lower not in bad_lines and len(line) > 5:
            return line

    return clean_text(text)


async def block_heavy_resources(route):
    request = route.request

    if request.resource_type in {
        "image",
        "media",
        "font",
        "stylesheet",
    }:
        await route.abort()
    else:
        await route.continue_()


async def parse_jobs_from_page(page) -> list[dict]:
    links = await page.locator('a[href*="JobDetail"]').evaluate_all(
        """
        els => els.map(a => {
            const card =
                a.closest("li") ||
                a.closest("article") ||
                a.closest("[class*='job']") ||
                a.closest("[class*='Job']") ||
                a.closest("tr") ||
                a.closest("div");

            return {
                href: a.href,
                linkText: a.innerText || "",
                cardText: card ? card.innerText : ""
            };
        })
        """
    )

    jobs = []
    seen_ids_on_page = set()

    for item in links:
        href = item.get("href", "")
        url = urljoin(BASE_URL, href)
        job_id = extract_job_id(url)

        if not job_id or job_id in seen_ids_on_page:
            continue

        text = item.get("cardText") or item.get("linkText") or ""
        title = clean_title(item.get("linkText") or text)

        if not title:
            continue

        seen_ids_on_page.add(job_id)

        jobs.append(
            {
                "company": "Siemens Healthineers",
                "job_id": job_id,
                "title": title,
                "location": "",
                "job_function": "",
                "career_level": "",
                "job_type": "",
                "posted_on": "",
                "url": url,
                "raw_text": clean_text(text),
            }
        )

    return jobs


async def scrape_listing_pages(page) -> list[dict]:
    all_jobs = []
    seen_ids = set()
    seen_page_signatures = set()

    for page_index in range(MAX_PAGES):
        offset = page_index * PAGE_SIZE
        url = make_page_url(offset)

        print(f"Scraping listing page {page_index + 1}: offset={offset}")

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45_000,
            )

            await page.wait_for_selector(
                'a[href*="JobDetail"]',
                timeout=20_000,
            )

        except PlaywrightTimeoutError:
            print("  Timeout or no jobs found. Stopping.")
            break

        page_jobs = await parse_jobs_from_page(page)

        if not page_jobs:
            print("  No jobs parsed. Stopping.")
            break

        page_signature = tuple(job["job_id"] for job in page_jobs)

        if page_signature in seen_page_signatures:
            print("  Duplicate page detected. Stopping.")
            break

        seen_page_signatures.add(page_signature)

        new_count = 0

        for job in page_jobs:
            if job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            all_jobs.append(job)
            new_count += 1

        print(f"  Added {new_count} new jobs")

        if new_count == 0:
            break

        if len(page_jobs) < PAGE_SIZE:
            break

    return all_jobs


async def get_page_text(page) -> str:
    return await page.locator("body").inner_text(timeout=20_000)


def extract_label_value(lines: list[str], labels: list[str]) -> str:
    normalized_labels = [label.lower().rstrip(":") for label in labels]

    for index, line in enumerate(lines):
        line_clean = clean_text(line)
        lower = line_clean.lower()

        for label in normalized_labels:
            # Handles: "Job ID: 123456"
            if lower.startswith(label + ":"):
                return clean_text(line_clean.split(":", 1)[1])

            # Handles:
            # Job ID
            # 123456
            if lower.rstrip(":") == label:
                for next_line in lines[index + 1 : index + 5]:
                    value = clean_text(next_line)
                    if value and value.lower().rstrip(":") not in normalized_labels:
                        return value

    return ""


def parse_detail_text(text: str) -> dict:
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]

    title = ""
    for line in lines:
        lower = line.lower()
        if lower not in {"apply", "share", "job details", "save job"} and len(line) > 8:
            title = line
            break

    job_id = extract_label_value(
        lines,
        [
            "Job ID",
            "Req ID",
            "Requisition ID",
            "Requisition Number",
        ],
    )

    location = extract_label_value(
        lines,
        [
            "Location",
            "Locations",
            "Standort",
        ],
    )

    job_function = extract_label_value(
        lines,
        [
            "Job Family",
            "Job Function",
            "Function",
            "Department",
        ],
    )

    career_level = extract_label_value(
        lines,
        [
            "Experience Level",
            "Career Level",
            "Seniority Level",
        ],
    )

    job_type = extract_label_value(
        lines,
        [
            "Job Type",
            "Employment Type",
            "Type of Employment",
        ],
    )

    posted_on = extract_label_value(
        lines,
        [
            "Date Posted",
            "Posted Date",
            "Posting Date",
            "Posted",
        ],
    )

    return {
        "title": title,
        "job_id": job_id,
        "location": location,
        "job_function": job_function,
        "career_level": career_level,
        "job_type": job_type,
        "posted_on": parse_date(posted_on),
    }


async def enrich_one_job(context, semaphore, job: dict) -> dict:
    async with semaphore:
        page = await context.new_page()

        try:
            await page.goto(
                job["url"],
                wait_until="domcontentloaded",
                timeout=45_000,
            )

            text = await get_page_text(page)
            detail = parse_detail_text(text)

            enriched = {**job}

            for key, value in detail.items():
                if value:
                    enriched[key] = value

            if not enriched.get("job_id"):
                enriched["job_id"] = extract_job_id(enriched["url"])

            return enriched

        except Exception as exc:
            print(f"Warning: failed detail page {job['url']}: {exc}")
            return job

        finally:
            await page.close()


async def enrich_jobs(context, jobs: list[dict]) -> list[dict]:
    semaphore = asyncio.Semaphore(MAX_DETAIL_CONCURRENCY)

    tasks = [enrich_one_job(context, semaphore, job) for job in jobs]

    return await asyncio.gather(*tasks)


async def scrape_siemens_healthineers() -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            ),
            viewport={
                "width": 1440,
                "height": 1000,
            },
            extra_http_headers={
                "accept-language": "en-US,en;q=0.9,de;q=0.8",
            },
        )

        await context.route("**/*", block_heavy_resources)

        listing_page = await context.new_page()

        try:
            jobs = await scrape_listing_pages(listing_page)
            print(f"Parsed {len(jobs)} jobs from listing pages")

            jobs = await enrich_jobs(context, jobs)
            print(f"Enriched {len(jobs)} jobs from detail pages")

        finally:
            await listing_page.close()
            await browser.close()

    return jobs


async def main():
    jobs = await scrape_siemens_healthineers()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
