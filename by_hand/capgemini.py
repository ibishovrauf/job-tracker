import asyncio
import json
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright

API_URL = "https://cg-jobstream-api.azurewebsites.net/api/job-search"
BASE_URL = "https://www.capgemini.com"
OUTPUT_FILE = "capgemini_de_student_jobs_first_page.json"


PARAMS = {
    "experience_level": "Student*innen",
    "country_code": "de-de,DE",
    "page": "1",
    "size": "11",
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
    candidates = []

    def walk(node: Any):
        if isinstance(node, list):
            dict_items = [x for x in node if isinstance(x, dict)]
            if dict_items:
                sample = dict_items[0]
                score = 0
                for key in sample.keys():
                    lk = key.lower()
                    if any(term in lk for term in ["job", "title", "location", "city", "country"]):
                        score += 1
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
        return ", ".join(str(x) for x in value if x not in (None, "")) or None

    if isinstance(value, dict):
        nested = first_value(value, ["label", "name", "value", "text", "title"])
        return as_text(nested)

    return str(value).strip() or None


def normalize_url(raw_url: Optional[str], job_id: Optional[str]) -> Optional[str]:
    if raw_url:
        if raw_url.startswith("http"):
            return raw_url
        return urljoin(BASE_URL, raw_url)

    return None


def normalize_location(
    raw: dict,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    location = as_text(
        first_value(
            raw,
            [
                "location",
                "locations",
                "jobLocation",
                "displayLocation",
                "formattedLocation",
            ],
        )
    )

    city = as_text(
        first_value(
            raw,
            [
                "city",
                "town",
                "jobCity",
            ],
        )
    )

    state = as_text(
        first_value(
            raw,
            [
                "state",
                "province",
                "region",
                "jobState",
            ],
        )
    )

    country = (
        as_text(
            first_value(
                raw,
                [
                    "country",
                    "countryName",
                    "jobCountry",
                ],
            )
        )
        or "Germany"
    )

    if not location:
        parts = [city, state, country]
        location = ", ".join(part for part in parts if part)

    return location, city, state, country


def normalize_job(raw: dict) -> dict:
    job_id = as_text(
        first_value(
            raw,
            [
                "id",
                "jobId",
                "job_id",
                "jobCode",
                "reference",
                "referenceNumber",
                "requisitionId",
                "reqId",
            ],
        )
    )

    title = as_text(
        first_value(
            raw,
            [
                "title",
                "jobTitle",
                "name",
                "positionTitle",
            ],
        )
    )

    location, city, state, country = normalize_location(raw)

    category = as_text(
        first_value(
            raw,
            [
                "category",
                "jobCategory",
                "profession",
                "businessUnit",
                "department",
                "function",
            ],
        )
    )

    sub_category = as_text(
        first_value(
            raw,
            [
                "subCategory",
                "sub_category",
                "specialism",
                "discipline",
                "practice",
            ],
        )
    )

    experience_level = as_text(
        first_value(
            raw,
            [
                "experience_level",
                "experienceLevel",
                "seniority",
                "level",
            ],
        )
    )

    posted_date = as_text(
        first_value(
            raw,
            [
                "posted_date",
                "postedDate",
                "datePosted",
                "publicationDate",
                "createdAt",
                "updatedAt",
            ],
        )
    )

    raw_url = as_text(
        first_value(
            raw,
            [
                "url",
                "jobUrl",
                "applyUrl",
                "canonicalUrl",
                "link",
            ],
        )
    )

    return {
        "company": "Capgemini",
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


async def main():
    async with async_playwright() as p:
        request = await p.request.new_context(
            extra_http_headers={
                "accept": "application/json, text/plain, */*",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
        )

        response = await request.get(API_URL, params=PARAMS)

        print("Status:", response.status)
        print("URL:", response.url)

        text = await response.text()

        print("\n--- First API response debug preview ---")
        print(text[:4000])

        if not response.ok:
            raise RuntimeError(f"Capgemini API request failed with status {response.status}")

        data = json.loads(text)

        raw_jobs = find_job_list(data)
        jobs = [normalize_job(job) for job in raw_jobs[: int(PARAMS["size"])]]

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(f"\nFound {len(raw_jobs)} raw jobs")
        print(f"Saved {len(jobs)} normalized jobs to {OUTPUT_FILE}")

        await request.dispose()


if __name__ == "__main__":
    asyncio.run(main())
