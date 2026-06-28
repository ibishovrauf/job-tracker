import asyncio
import json
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright

API_URL = "https://pcw-api.softgarden.de/widgets/job-list/job-ads"
BASE_URL = "https://jobs.softgarden.de"
OUTPUT_FILE = "softgarden_student_jobs_first_page.json"


PAYLOAD = {
    "userId": "faad2448-ef57-484b-b397-6a212f28a800",
    "projectId": "17979f79-39e6-4bf7-8f6d-7d5dba7a01f8",
    "pageId": "06d0a88d-3b56-45b3-b867-7a4d39d775ef",
    "locale": "de",
    "listState": {
        "search": "",
        "disableSearchInDescription": False,
        "location": {
            "osmLocation": "",
            "range": 25,
            "coords": [],
        },
        "filters": {
            "careerLevel": ["Student/in"],
            "category": [],
            "location": [],
            "company": [],
            "partnership": [],
            "region": [],
            "country": [],
            "workTime": [],
            "remoteStatus": [],
            "workExperience": [],
            "employmentType": [],
        },
    },
    "isActiveCustomJobPages": True,
    "isUseLayoutsOfSubsidiaries": False,
    "filterStatus": {
        "careerLevel": True,
        "category": True,
        "partnership": False,
        "region": False,
        "location": True,
        "company": True,
        "country": False,
        "workTime": False,
        "remoteStatus": False,
        "workExperience": False,
        "employmentType": False,
    },
    "numberOfJobsOnPage": 12,
    "pageNumber": "1",
    "isForCurrentLocale": False,
    "isGetFilters": True,
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
                    if any(x in lk for x in ["job", "title", "location", "career", "company"]):
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


def normalize_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url:
        return None

    if raw_url.startswith("http"):
        return raw_url

    return urljoin(BASE_URL, raw_url)


def normalize_job(raw: dict) -> dict:
    job_id = as_text(
        first_value(
            raw,
            [
                "id",
                "jobAdId",
                "jobId",
                "externalPostingId",
                "postingId",
                "referenceNumber",
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
            ],
        )
    )

    location = as_text(
        first_value(
            raw,
            [
                "location",
                "locations",
                "workplace",
                "office",
                "city",
            ],
        )
    )

    city = as_text(
        first_value(
            raw,
            [
                "city",
                "locationName",
                "workplace",
            ],
        )
    )

    state = as_text(
        first_value(
            raw,
            [
                "state",
                "region",
                "province",
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
                ],
            )
        )
        or "Germany"
    )

    category = as_text(
        first_value(
            raw,
            [
                "category",
                "jobCategory",
                "department",
            ],
        )
    )

    sub_category = as_text(
        first_value(
            raw,
            [
                "subCategory",
                "sub_category",
                "function",
                "team",
            ],
        )
    )

    experience_level = as_text(
        first_value(
            raw,
            [
                "careerLevel",
                "experienceLevel",
                "level",
            ],
        )
    )

    posted_date = as_text(
        first_value(
            raw,
            [
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
                "detailUrl",
                "applyUrl",
                "link",
            ],
        )
    )

    return {
        "company": "PCW",
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
        "url": normalize_url(raw_url),
    }


async def main():
    async with async_playwright() as p:
        request = await p.request.new_context(
            extra_http_headers={
                "accept": "application/json, text/plain, */*",
                "content-type": "application/json",
                "origin": "https://pcw.softgarden.io",
                "referer": "https://pcw.softgarden.io/",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
        )

        response = await request.post(API_URL, data=PAYLOAD)

        print("Status:", response.status)
        print("URL:", response.url)

        text = await response.text()

        print("\n--- First API response debug preview ---")
        print(text[:4000])

        if not response.ok:
            raise RuntimeError(f"Softgarden API request failed with status {response.status}")

        data = json.loads(text)

        raw_jobs = find_job_list(data)
        jobs = [normalize_job(job) for job in raw_jobs[: int(PAYLOAD["numberOfJobsOnPage"])]]

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(f"\nFound {len(raw_jobs)} raw jobs")
        print(f"Saved {len(jobs)} normalized jobs to {OUTPUT_FILE}")

        await request.dispose()


if __name__ == "__main__":
    asyncio.run(main())
