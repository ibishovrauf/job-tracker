import asyncio
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote, urljoin

from playwright.async_api import async_playwright

API_URL_PART = "/api/v1/job/search"
API_URL = "https://jobs.schwarz/api/v1/job/search"
BASE_URL = "https://jobs.schwarz"

SEARCH_TERM = "Werkstudent"
JOBSEARCH_URL = f"https://jobs.schwarz/jobsearch?term={quote(SEARCH_TERM)}"

OUTPUT_FILE = "schwarz_jobs.json"
PAYLOAD_DEBUG_FILE = "schwarz_payload.json"
API_CALLS_DEBUG_FILE = "schwarz_api_calls_debug.json"

PER_PAGE = 10
MAX_PAGES = 100

WERKSTUDENT_TERMS = [
    "werkstudent",
    "werkstudentin",
    "working student",
]


def clean_text(value) -> str:
    if value is None:
        return ""

    if isinstance(value, list):
        parts = [clean_text(item) for item in value]
        return ", ".join(part for part in parts if part)

    if isinstance(value, dict):
        parts = []
        for item in value.values():
            if isinstance(item, (str, int, float, list, dict)):
                text = clean_text(item)
                if text:
                    parts.append(text)
        return ", ".join(parts)

    return " ".join(str(value).replace("\xa0", " ").split())


def object_contains_term(obj, term: str) -> bool:
    return term.lower() in json.dumps(obj, ensure_ascii=False).lower()


def is_werkstudent_job(job: dict) -> bool:
    text = json.dumps(job, ensure_ascii=False).lower()
    return any(term in text for term in WERKSTUDENT_TERMS)


def remove_key_recursively(obj, key: str) -> None:
    if isinstance(obj, dict):
        obj.pop(key, None)

        for value in obj.values():
            remove_key_recursively(value, key)

    elif isinstance(obj, list):
        for item in obj:
            remove_key_recursively(item, key)


def replace_key_recursively(obj, key: str, value) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            obj[key] = value
            return True

        for child in obj.values():
            if replace_key_recursively(child, key, value):
                return True

    elif isinstance(obj, list):
        for child in obj:
            if replace_key_recursively(child, key, value):
                return True

    return False


def build_payload(base_payload: dict, page: int) -> dict:
    payload = deepcopy(base_payload)

    # Request uses perPage.
    # Response uses resultsPerPage.
    # The API rejects resultsPerPage in the request body.
    remove_key_recursively(payload, "resultsPerPage")

    if not replace_key_recursively(payload, "page", page):
        payload["page"] = page

    if not replace_key_recursively(payload, "perPage", PER_PAGE):
        payload["perPage"] = PER_PAGE

    return payload


def deep_find_first(obj, keys: list[str]) -> str:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                value = clean_text(obj[key])
                if value:
                    return value

        for value in obj.values():
            found = deep_find_first(value, keys)
            if found:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = deep_find_first(item, keys)
            if found:
                return found

    return ""


def make_absolute_url(value: str) -> str:
    value = clean_text(value)

    if not value:
        return ""

    if value.startswith("http://") or value.startswith("https://"):
        return value

    return urljoin(BASE_URL, value)


def normalize_job(raw_job: dict) -> dict:
    job_id = deep_find_first(
        raw_job,
        [
            "id",
            "jobId",
            "job_id",
            "jobNumber",
            "job_number",
            "reference",
            "referenceNumber",
            "externalId",
            "identifier",
        ],
    )

    title = deep_find_first(
        raw_job,
        [
            "title",
            "name",
            "jobTitle",
            "job_title",
            "headline",
        ],
    )

    location = deep_find_first(
        raw_job,
        [
            "location",
            "locations",
            "city",
            "place",
            "workplace",
            "workLocation",
            "work_location",
        ],
    )

    employment_area = deep_find_first(
        raw_job,
        [
            "employment_area",
            "employmentArea",
            "employmentAreaName",
            "employmentAreaTitle",
            "employmentAreaTitleText",
            "careerLevel",
            "career_level",
        ],
    )

    company = deep_find_first(
        raw_job,
        [
            "company",
            "brand",
            "organization",
            "legalEntity",
            "legal_entity",
            "employer",
        ],
    )

    posted_on = deep_find_first(
        raw_job,
        [
            "postedOn",
            "posted_on",
            "postingDate",
            "posting_date",
            "date",
            "publishedAt",
            "publicationDate",
        ],
    )

    url = deep_find_first(
        raw_job,
        [
            "url",
            "jobUrl",
            "job_url",
            "detailUrl",
            "detail_url",
            "canonicalUrl",
            "link",
            "path",
        ],
    )

    return {
        "company": company or "Schwarz",
        "job_id": job_id,
        "title": title,
        "location": location,
        "employment_area": employment_area,
        "posted_on": posted_on,
        "url": make_absolute_url(url),
        "raw": raw_job,
    }


async def block_heavy_resources(route):
    request = route.request

    if request.resource_type in {"image", "media", "font", "stylesheet"}:
        await route.abort()
    else:
        await route.continue_()


async def capture_search_payload_and_first_response(context) -> tuple[dict, dict]:
    page = await context.new_page()
    candidates = []

    async def on_response(response):
        if API_URL_PART not in response.url:
            return

        request = response.request

        if request.method.upper() != "POST":
            return

        try:
            post_data = request.post_data or "{}"
            payload = json.loads(post_data)
        except Exception:
            return

        try:
            data = await response.json()
        except Exception:
            return

        pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
        total_count = pagination.get("totalCount")

        candidate = {
            "payload": payload,
            "response": data,
            "has_search_term": object_contains_term(payload, SEARCH_TERM),
            "total_count": total_count,
        }

        candidates.append(candidate)

        print(
            "Captured API call:",
            f"has_term={candidate['has_search_term']}",
            f"total={candidate['total_count']}",
        )

    page.on("response", on_response)

    try:
        print(f"Opening {JOBSEARCH_URL}")

        await page.goto(
            JOBSEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        # Do not stop after the first API call.
        # Schwarz may first load unfiltered jobs, then run the searched request.
        await page.wait_for_timeout(12_000)

        if not candidates:
            raise RuntimeError(
                "Could not capture any /api/v1/job/search request. "
                "Try running with headless=False to see whether the page loads correctly."
            )

        Path(API_CALLS_DEBUG_FILE).write_text(
            json.dumps(candidates, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        term_candidates = [item for item in candidates if item["has_search_term"]]

        if term_candidates:
            chosen = term_candidates[-1]
            print("Using captured API payload that contains Werkstudent.")
        else:
            chosen = candidates[-1]
            print(
                "Warning: no captured API payload contained Werkstudent. "
                "Using latest payload and applying local Werkstudent filter after scraping."
            )

        Path(PAYLOAD_DEBUG_FILE).write_text(
            json.dumps(chosen["payload"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"Saved chosen payload to {PAYLOAD_DEBUG_FILE}")

        return chosen["payload"], chosen["response"]

    finally:
        await page.close()


async def fetch_page(request_context, base_payload: dict, page: int) -> dict:
    payload = build_payload(base_payload, page)

    response = await request_context.post(
        API_URL,
        data=json.dumps(payload),
        timeout=120_000,
        headers={
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": BASE_URL,
            "referer": JOBSEARCH_URL,
        },
    )

    text = await response.text()

    if not response.ok:
        raise RuntimeError(
            f"Schwarz request failed: HTTP {response.status}\n"
            f"Payload sent:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            f"Response:\n{text[:3000]}"
        )

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Response was not JSON:\n{text[:3000]}") from exc


def get_jobs(data: dict) -> list[dict]:
    jobs = data.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def get_pagination(data: dict) -> dict:
    pagination = data.get("pagination", {})
    return pagination if isinstance(pagination, dict) else {}


async def scrape_schwarz() -> list[dict]:
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
                "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        await context.route("**/*", block_heavy_resources)

        try:
            base_payload, first_data = await capture_search_payload_and_first_response(context)

            pagination = get_pagination(first_data)

            total_count = int(pagination.get("totalCount", 0) or 0)

            results_per_page = int(
                pagination.get("resultsPerPage") or pagination.get("perPage") or PER_PAGE
            )

            print(f"Schwarz reports {total_count} matching jobs")

            all_raw_jobs = get_jobs(first_data)

            if total_count:
                total_pages = (total_count + results_per_page - 1) // results_per_page
                total_pages = min(total_pages, MAX_PAGES)
            else:
                total_pages = 1

            request_context = context.request

            for page_number in range(2, total_pages + 1):
                print(f"Fetching Schwarz page {page_number}...")

                data = await fetch_page(
                    request_context=request_context,
                    base_payload=base_payload,
                    page=page_number,
                )

                page_jobs = get_jobs(data)

                if not page_jobs:
                    print("No more jobs returned. Stopping.")
                    break

                all_raw_jobs.extend(page_jobs)

        finally:
            await browser.close()

    normalized_jobs = []
    seen = set()

    for raw_job in all_raw_jobs:
        job = normalize_job(raw_job)

        key = (
            job.get("job_id")
            or job.get("url")
            or json.dumps(raw_job, sort_keys=True, ensure_ascii=False)
        )

        if key in seen:
            continue

        seen.add(key)
        normalized_jobs.append(job)

    return normalized_jobs


async def main():
    jobs = await scrape_schwarz()

    before = len(jobs)
    jobs = [job for job in jobs if is_werkstudent_job(job)]

    print(f"Filtered {before} jobs down to {len(jobs)} Werkstudent jobs")

    Path(OUTPUT_FILE).write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
