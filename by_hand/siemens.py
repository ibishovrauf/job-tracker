import asyncio
import json
import re
from urllib.parse import urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

BASE_URL = "https://jobs.siemens.com"

START_URL = (
    "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/"
    "?42386=%5B812132%5D"
    "&42386_format=17546"
    "&42390=%5B102154%5D"
    "&42390_format=17550"
    "&listFilterMode=1"
    "&folderSort=postedDate"
    "&folderSortDirection=ASC"
    "&folderRecordsPerPage=6"
)

OUTPUT_FILE = "siemens_filtered_jobs.json"

PAGE_SIZE = 6
MAX_PAGES = 100

JOB_ID_RE = re.compile(
    r"/JobDetail/(?:.*?/)?(\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)


def make_page_url(offset: int) -> str:
    return f"{START_URL}&folderOffset={offset}"


def extract_job_id(url: str) -> str | None:
    match = JOB_ID_RE.search(url)
    return match.group(1) if match else None


def clean_title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    bad_lines = {
        "learn more",
        "share",
        "bewerben",
        "apply",
        "job details",
        "details",
        "save job",
        "saved job",
        "job speichern",
        "teilen",
    }

    for line in lines:
        if line.lower() not in bad_lines and len(line) > 5:
            return line

    return text.strip()


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
        job_id = extract_job_id(href)

        if not job_id or job_id in seen_ids_on_page:
            continue

        text = item.get("cardText") or item.get("linkText") or ""
        title = clean_title(text)

        if not title:
            continue

        seen_ids_on_page.add(job_id)

        jobs.append(
            {
                "company": "Siemens",
                "job_id": job_id,
                "title": title,
                "url": urljoin(BASE_URL, href),
                "raw_text": text.strip(),
            }
        )

    return jobs


async def scrape_siemens_filtered(page) -> list[dict]:
    all_jobs = []
    seen_ids = set()
    seen_page_signatures = set()

    for page_index in range(MAX_PAGES):
        offset = page_index * PAGE_SIZE
        url = make_page_url(offset)

        print(f"Scraping page {page_index + 1}...")

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            await page.wait_for_selector(
                'a[href*="JobDetail"]',
                timeout=15000,
            )

        except PlaywrightTimeoutError:
            print("  Timeout or no jobs found. Stopping.")
            break

        page_jobs = await parse_jobs_from_page(page)

        if not page_jobs:
            break

        page_signature = tuple(job["job_id"] for job in page_jobs)

        if page_signature in seen_page_signatures:
            break

        seen_page_signatures.add(page_signature)

        new_count = 0

        for job in page_jobs:
            if job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            all_jobs.append(job)
            new_count += 1

        print(f"  Added {new_count} jobs")

        if new_count == 0:
            break

        if len(page_jobs) < PAGE_SIZE:
            break

    return all_jobs


async def main():
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
        )

        await context.route("**/*", block_heavy_resources)

        page = await context.new_page()

        jobs = await scrape_siemens_filtered(page)

        await browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
