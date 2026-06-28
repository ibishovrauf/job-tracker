import asyncio
import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

API_URL = "https://www.pgcareers.com/widgets"
BASE_URL = "https://www.pgcareers.com"
REFERER_URL = "https://www.pgcareers.com/de/en/search-results"

OUTPUT_FILE = "pgcareers_first_page_jobs.json"

PAYLOAD = {
    "lang": "en_de",
    "deviceType": "desktop",
    "country": "de",
    "pageName": "search-results",
    "ddoKey": "eagerLoadRefineSearch",
    "sortBy": "Most recent",
    "subsearch": "",
    "from": 0,
    "irs": False,
    "jobs": True,
    "counts": True,
    "all_fields": [
        "category",
        "country",
        "state",
        "city",
        "type",
        "subCategory",
        "experienceLevel",
        "phLocSlider",
    ],
    "size": 10,
    "clearAll": False,
    "jdsource": "facets",
    "isSliderEnable": True,
    "pageId": "page16-ds",
    "siteType": "external",
    "keywords": "",
    "global": True,
    "selected_fields": {
        "country": ["Germany"],
        "experienceLevel": ["Internships"],
    },
    "sort": {
        "order": "desc",
        "field": "postedDate",
    },
    "locationData": {
        "sliderRadius": 50,
        "aboveMaxRadius": True,
        "LocationUnit": "miles",
    },
    "s": "1",
}


def clean_text(value) -> str:
    if value is None:
        return ""

    if isinstance(value, list):
        return ", ".join(clean_text(v) for v in value if clean_text(v))

    if isinstance(value, dict):
        return ", ".join(clean_text(v) for v in value.values() if clean_text(v))

    return " ".join(str(value).replace("\xa0", " ").split())


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


def get_jobs(data: dict) -> list[dict]:
    candidates = [
        data.get("eagerLoadRefineSearch", {}).get("data", {}).get("jobs"),
        data.get("eagerLoadRefineSearch", {}).get("jobs"),
        data.get("jobs"),
    ]

    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate

    return []


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
        ["jobId", "job_id", "id", "reqId", "req_id", "referenceNumber"],
    )

    title = deep_find_first(
        raw_job,
        ["title", "jobTitle", "job_title", "name"],
    )

    city = deep_find_first(raw_job, ["city"])
    state = deep_find_first(raw_job, ["state"])
    country = deep_find_first(raw_job, ["country"])
    location = deep_find_first(raw_job, ["location", "jobLocation", "job_location"])

    url = deep_find_first(
        raw_job,
        ["url", "jobUrl", "job_url", "applyUrl", "apply_url", "externalApplyUrl"],
    )

    return {
        "company": "Procter & Gamble",
        "job_id": job_id,
        "title": title,
        "location": location or ", ".join(x for x in [city, state, country] if x),
        "city": city,
        "state": state,
        "country": country,
        "category": deep_find_first(raw_job, ["category"]),
        "sub_category": deep_find_first(raw_job, ["subCategory", "sub_category"]),
        "experience_level": deep_find_first(raw_job, ["experienceLevel"]),
        "posted_date": deep_find_first(raw_job, ["postedDate", "posted_date", "date"]),
        "url": make_absolute_url(url),
        "raw": raw_job,
    }


async def scrape_pgcareers_first_page() -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1000},
            extra_http_headers={
                "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        response = await context.request.post(
            API_URL,
            data=json.dumps(PAYLOAD),
            headers={
                "accept": "application/json, text/javascript, */*; q=0.01",
                "content-type": "application/json",
                "origin": BASE_URL,
                "referer": REFERER_URL,
                "x-requested-with": "XMLHttpRequest",
            },
            timeout=120_000,
        )

        text = await response.text()
        await browser.close()

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status}\n{text[:3000]}")

        data = json.loads(text)
        raw_jobs = get_jobs(data)

        jobs = [normalize_job(job) for job in raw_jobs]

        return jobs


async def main():
    jobs = await scrape_pgcareers_first_page()

    Path(OUTPUT_FILE).write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
