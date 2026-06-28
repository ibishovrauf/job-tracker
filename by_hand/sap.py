import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_URL = "https://jobs.sap.com"

# SAP Careers listing for Intern Jobs in Germany:
# https://jobs.sap.com/go/Intern-Jobs-in-Germany/902401/
LIST_PATH = "/go/Intern-Jobs-in-Germany/902401/"

OUTPUT_FILE = "sap_jobs.json"

PAGE_SIZE = 25
MAX_JOBS = 2000
MAX_CONCURRENCY = 5

SORT_PARAMS = {
    "q": "",
    "sortColumn": "referencedate",
    "sortDirection": "desc",
}


def build_list_url(start_row: int) -> str:
    """
    SAP pagination uses the row offset in the path:
      page 1: /go/Intern-Jobs-in-Germany/902401/
      page 2: /go/Intern-Jobs-in-Germany/902401/25/
      page 3: /go/Intern-Jobs-in-Germany/902401/50/
    """
    if start_row == 0:
        path = LIST_PATH
    else:
        path = f"{LIST_PATH.rstrip('/')}/{start_row}/"

    return f"{urljoin(BASE_URL, path)}?{urlencode(SORT_PARAMS)}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def parse_sap_date(value: str) -> str:
    value = clean_text(value)

    if not value:
        return ""

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass

    return value


def extract_job_id(url: str) -> str:
    """
    SAP job URLs usually end with a numeric requisition-like ID:
      /job/Walldorf-Some-Title-69190/1277604601/
    """
    path = urlparse(url).path.strip("/")
    match = re.search(r"/(\d+)/?$", "/" + path)
    return match.group(1) if match else ""


def parse_total_count(soup: BeautifulSoup) -> int | None:
    text = soup.get_text(" ", strip=True)

    # Example: Results 1 – 25 of 94 Page 1 of 4
    match = re.search(r"Results\s+\d+\s*[–-]\s*\d+\s+of\s+(\d+)", text)
    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def parse_location_from_row(row, title: str) -> str:
    if not row:
        return ""

    for selector in (
        ".jobLocation",
        ".colLocation",
        "td.colLocation",
        "span[class*='location']",
        "td[class*='Location']",
    ):
        element = row.select_one(selector)
        if element:
            location = clean_text(element.get_text(" ", strip=True))
            if location:
                return location

    cells = row.find_all("td")
    if len(cells) >= 2:
        for cell in cells[1:]:
            text = clean_text(cell.get_text(" ", strip=True))
            if text and text != title and not text.lower().startswith("title"):
                return text

    return ""


def parse_jobs_and_total(html: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    total = parse_total_count(soup)

    jobs = []
    seen_ids = set()

    for link in soup.select('a[href*="/job/"]'):
        href = link.get("href", "")
        url = urljoin(BASE_URL, href)
        job_id = extract_job_id(url)
        title = clean_text(link.get_text(" ", strip=True))

        if not job_id or not title:
            continue

        if job_id in seen_ids:
            continue

        seen_ids.add(job_id)

        row = link.find_parent("tr") or link.find_parent(["li", "div"])
        location = parse_location_from_row(row, title)

        jobs.append(
            {
                "company": "SAP",
                "job_id": job_id,
                "requisition_id": "",
                "title": title,
                "location": location,
                "legal_entity": "",
                "job_field": "",
                "career_status": "",
                "job_type": "",
                "employment_type": "",
                "expected_travel": "",
                "posted_on": "",
                "url": url,
            }
        )

    return jobs, total


def parse_key_value_segments(lines: list[str]) -> dict:
    data = {}

    wanted = {
        "Requisition ID": "requisition_id",
        "Posted Date": "posted_on_raw",
        "Work Area": "job_field",
        "Career Status": "career_status",
        "Employment Type": "employment_type",
        "Expected Travel": "expected_travel",
    }

    for line in lines:
        # SAP sometimes puts fields in one pipe-separated line:
        # Requisition ID: 443521 | Work Area: Administration | ...
        segments = re.split(r"\s*\|\s*", line)

        for segment in segments:
            for label, key in wanted.items():
                pattern = rf"^{re.escape(label)}:\s*(.+)$"
                match = re.match(pattern, segment)
                if match:
                    data[key] = clean_text(match.group(1))

    return data


def parse_location_from_detail(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if clean_text(line).rstrip(":") == "Location":
            for next_line in lines[index + 1 : index + 4]:
                location = clean_text(next_line)
                if location and not location.lower().startswith("job alert"):
                    return location

    return ""


def parse_job_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one("h1")
    title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""

    lines = [
        clean_text(line)
        for line in soup.get_text("\n", strip=True).splitlines()
        if clean_text(line)
    ]

    data = parse_key_value_segments(lines)

    posted_on = parse_sap_date(data.pop("posted_on_raw", ""))

    detail = {
        "title": title,
        "requisition_id": data.get("requisition_id", ""),
        "job_field": data.get("job_field", ""),
        "career_status": data.get("career_status", ""),
        "job_type": data.get("employment_type", ""),
        "employment_type": data.get("employment_type", ""),
        "expected_travel": data.get("expected_travel", ""),
        "posted_on": posted_on,
        "location": parse_location_from_detail(lines),
    }

    return {key: value for key, value in detail.items() if value}


async def fetch_html(request_context, url: str) -> str:
    response = await request_context.get(
        url,
        timeout=120_000,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": "https://jobs.sap.com/",
        },
    )

    if not response.ok:
        raise RuntimeError(f"SAP request failed: HTTP {response.status} for {url}")

    return await response.text()


async def fetch_detail_with_limit(request_context, semaphore, job: dict) -> dict:
    async with semaphore:
        try:
            html = await fetch_html(request_context, job["url"])
            detail = parse_job_detail(html)

            enriched = {**job}

            for key, value in detail.items():
                if value:
                    enriched[key] = value

            if not enriched.get("job_id") and enriched.get("requisition_id"):
                enriched["job_id"] = enriched["requisition_id"]

            return enriched

        except Exception as exc:
            print(f"Warning: failed to fetch detail for {job['url']}: {exc}")
            return job


async def scrape_sap(request_context) -> list[dict]:
    print("Fetching first SAP page...")

    first_url = build_list_url(0)
    first_html = await fetch_html(request_context, first_url)

    first_jobs, total = parse_jobs_and_total(first_html)

    if total is None:
        print("Could not detect total count; saving first page only.")
        list_jobs = first_jobs
    else:
        total = min(total, MAX_JOBS)
        print(f"SAP reports {total} matching jobs")

        offsets = list(range(PAGE_SIZE, total, PAGE_SIZE))

        async def fetch_page(offset: int) -> list[dict]:
            url = build_list_url(offset)
            html = await fetch_html(request_context, url)
            jobs, _ = parse_jobs_and_total(html)
            return jobs

        other_pages = await asyncio.gather(*(fetch_page(offset) for offset in offsets))

        list_jobs = first_jobs
        for page_jobs in other_pages:
            list_jobs.extend(page_jobs)

    deduped = []
    seen_ids = set()

    for job in list_jobs:
        job_id = job.get("job_id", "")
        if not job_id or job_id in seen_ids:
            continue

        seen_ids.add(job_id)
        deduped.append(job)

    print(f"Parsed {len(deduped)} SAP jobs from listing pages")
    print("Fetching SAP job detail pages for requisition IDs and posted dates...")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    enriched_jobs = await asyncio.gather(
        *(
            fetch_detail_with_limit(
                request_context=request_context,
                semaphore=semaphore,
                job=job,
            )
            for job in deduped
        )
    )

    return enriched_jobs


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
            jobs = await scrape_sap(request_context)
        finally:
            await request_context.dispose()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
