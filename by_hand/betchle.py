import asyncio
import json
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright

COMPANY = "Bechtle"
API_URL = "https://production.api.recruiting-solutions.org/search"
SEARCH_PAGE_URL = (
    "https://jobs.bechtle.com/?currentPage=1&pageSize=12"
    "&addresses%2Fcountry=Deutschland"
    "&entryLevel%2Flabel=Praktikum"
    "&entryLevel%2Flabel=Werkstudent%3Ainnent%C3%A4tigkeit"
)
BASE_URL = "https://jobs.bechtle.com"
OUTPUT_FILE = "bechtle_de_student_jobs_first_page.json"


PAYLOAD = {
    "count": True,
    "facets": [],
    "filter": (
        "datePosted lt 2026-06-08T23:27:15.802Z "
        "and (addresses/any(jt: jt/country eq 'Deutschland')) "
        "and (entryLevel/label eq 'Praktikum' or entryLevel/label eq 'Werkstudent:innentätigkeit') "
        "and language eq 'de_DE'"
    ),
    "search": "*",
    "searchFields": (
        "jobId,title,description,addresses/city,addresses/country,"
        "entryLevel/label,jobFunction/label,workingTime/label,"
        "contractType/label,legal/entityName"
    ),
    "skip": 0,
    "top": 100,
}


def first_value(obj: Any, keys: list[str]) -> Optional[Any]:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, "", []):
                return obj[key]

        lower_map = {k.lower(): k for k in obj.keys()}
        for key in keys:
            real_key = lower_map.get(key.lower())
            if real_key and obj[real_key] not in (None, "", []):
                return obj[real_key]

        for value in obj.values():
            found = first_value(value, keys)
            if found not in (None, "", []):
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = first_value(item, keys)
            if found not in (None, "", []):
                return found

    return None


def find_job_list(obj: Any) -> list[dict]:
    if isinstance(obj, dict):
        for key in ["value", "jobs", "results", "items", "data"]:
            if isinstance(obj.get(key), list):
                return [x for x in obj[key] if isinstance(x, dict)]

    candidates = []

    def walk(node: Any):
        if isinstance(node, list):
            dict_items = [x for x in node if isinstance(x, dict)]
            if dict_items:
                sample = dict_items[0]
                score = sum(
                    1
                    for k in sample.keys()
                    if any(x in k.lower() for x in ["job", "title", "address", "entry", "legal"])
                )
                candidates.append((score, len(dict_items), dict_items))

            for item in node:
                walk(item)

        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(obj)

    if not candidates:
        return []

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2]


def as_text(value: Any) -> Optional[str]:
    if value in (None, "", []):
        return None

    if isinstance(value, list):
        parts = [as_text(v) for v in value]
        return ", ".join(v for v in parts if v) or None

    if isinstance(value, dict):
        nested = first_value(value, ["label", "name", "value", "text", "city", "country"])
        return as_text(nested)

    return str(value).strip() or None


def normalize_url(raw_url: Optional[str], job_id: Optional[str]) -> Optional[str]:
    if raw_url:
        if raw_url.startswith("http"):
            return raw_url
        return urljoin(BASE_URL, raw_url)

    if job_id:
        return f"{BASE_URL}/job/{job_id}"

    return None


def normalize_job(raw: dict) -> dict:
    job_id = as_text(first_value(raw, ["jobId", "job_id", "id", "requisitionId", "reqId"]))
    title = as_text(first_value(raw, ["title", "jobTitle", "name"]))

    addresses = first_value(raw, ["addresses"])
    location = as_text(addresses)

    city = as_text(first_value(raw, ["city", "addresses/city"]))
    state = as_text(first_value(raw, ["state", "region", "province"]))
    country = as_text(first_value(raw, ["country", "addresses/country"])) or "Deutschland"

    category = as_text(first_value(raw, ["jobFunction", "category", "jobCategory", "department"]))
    sub_category = as_text(
        first_value(raw, ["contractType", "workingTime", "subCategory", "sub_category"])
    )
    experience_level = as_text(first_value(raw, ["entryLevel", "experienceLevel", "level"]))
    posted_date = as_text(
        first_value(raw, ["datePosted", "postedDate", "posted_date", "createdAt", "updatedAt"])
    )

    raw_url = as_text(first_value(raw, ["url", "jobUrl", "applyUrl", "detailUrl", "link"]))

    return {
        "company": COMPANY,
        "job_id": job_id,
        "title": title,
        "location": location,
        "city": city,
        "state": state,
        "country": country,
        "category": category,
        "sub_category": sub_category,
        "experience_level": experience_level,
        "posted_date": posted_date,
        "url": normalize_url(raw_url, job_id),
    }


async def capture_api_headers(playwright) -> dict:
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    captured: dict[str, Any] = {}

    async def on_request(request):
        if request.url.startswith(API_URL) and request.method == "POST":
            captured["headers"] = dict(request.headers)

    page.on("request", on_request)

    await page.goto(SEARCH_PAGE_URL, wait_until="networkidle", timeout=60000)
    await browser.close()

    if "headers" not in captured:
        raise RuntimeError("Could not capture Bechtle API headers from browser request.")

    headers = captured["headers"]

    for header in [
        "host",
        "connection",
        "content-length",
        "accept-encoding",
        "cookie",
    ]:
        headers.pop(header, None)

    headers["accept"] = "application/json"
    headers["content-type"] = "application/json"
    headers["origin"] = BASE_URL
    headers["referer"] = BASE_URL + "/"

    print("\n--- Captured API header debug ---")
    for key, value in headers.items():
        if "customer" in key.lower() or "tenant" in key.lower() or "auth" in key.lower():
            print(f"{key}: {value}")

    return headers


async def main():
    async with async_playwright() as p:
        headers = await capture_api_headers(p)

        request = await p.request.new_context(extra_http_headers=headers)
        response = await request.post(API_URL, data=PAYLOAD)

        print("Status:", response.status)
        print("URL:", response.url)

        text = await response.text()

        print("\n--- First API response debug preview ---")
        print(text[:4000])

        if not response.ok:
            raise RuntimeError(f"Bechtle API request failed with status {response.status}")

        data = json.loads(text)
        raw_jobs = find_job_list(data)
        jobs = [normalize_job(job) for job in raw_jobs[: PAYLOAD["top"]]]

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(f"\nFound {len(raw_jobs)} raw jobs")
        print(f"Saved {len(jobs)} normalized jobs to {OUTPUT_FILE}")

        await request.dispose()


if __name__ == "__main__":
    asyncio.run(main())
