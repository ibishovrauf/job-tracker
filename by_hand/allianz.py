import asyncio
import json
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright

BASE_URL = "https://careers.allianz.com"
SEARCH_URL = f"{BASE_URL}/en_global/search-results"
API_URL = f"{BASE_URL}/widgets"

OUTPUT_FILE = "allianz_de_student_jobs_first_page.json"


PAYLOAD = {
    "sortBy": "Most recent",
    "subsearch": "",
    "from": 0,
    "jobs": True,
    "counts": True,
    "all_fields": [
        "phLocSlider",
        "category",
        "country",
        "state",
        "city",
        "remote",
        "employmentType",
        "jobLevel",
        "type",
        "unit",
    ],
    "pageName": "search-results",
    "size": 200,
    "clearAll": False,
    "jdsource": "facets",
    "isSliderEnable": True,
    "pageId": "page3",
    "siteType": "external",
    "keywords": "",
    "global": True,
    "selected_fields": {
        "country": ["Germany"],
        "jobLevel": ["Student"],
        "category": ["Data & AI"],
    },
    "sort": {"order": "desc", "field": "postedDate"},
    "locationData": {
        "sliderRadius": 50,
        "aboveMaxRadius": False,
        "LocationUnit": "miles",
    },
    "s": "1",
    "lang": "en_global",
    "deviceType": "desktop",
    "country": "global",
    "refNum": "AISAIPGB",
    "ddoKey": "eagerLoadRefineSearch",
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
                    if any(x in lk for x in ["job", "title", "req", "location", "city"]):
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
        nested = first_value(value, ["label", "name", "value", "text"])
        return as_text(nested)

    return str(value).strip() or None


def normalize_url(raw_url: Optional[str], job_id: Optional[str]) -> Optional[str]:
    if raw_url:
        if raw_url.startswith("http"):
            return raw_url
        return urljoin(BASE_URL, raw_url)

    if job_id:
        return f"{BASE_URL}/en_global/job/-/-/{job_id}"

    return None


def normalize_job(raw: dict) -> dict:
    job_id = as_text(
        first_value(
            raw,
            [
                "jobId",
                "job_id",
                "jobSeqNo",
                "reqId",
                "requisitionId",
                "atsJobId",
                "id",
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
                "jobLocation",
                "formattedLocation",
            ],
        )
    )

    city = as_text(
        first_value(
            raw,
            [
                "city",
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
            ],
        )
    )

    country = (
        as_text(
            first_value(
                raw,
                [
                    "country",
                    "jobCountry",
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
                "categoryNew",
                "jobCategory",
                "profession",
            ],
        )
    )

    sub_category = as_text(
        first_value(
            raw,
            [
                "subCategory",
                "sub_category",
                "subCategoryName",
                "specialism",
            ],
        )
    )

    experience_level = as_text(
        first_value(
            raw,
            [
                "jobLevel",
                "entryLevel",
                "experienceLevel",
                "experience_level",
                "level",
            ],
        )
    )

    posted_date = as_text(
        first_value(
            raw,
            [
                "postedDate",
                "posted_date",
                "datePosted",
                "displayDate",
                "createdDate",
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
                "externalUrl",
                "canonicalUrl",
            ],
        )
    )

    return {
        "company": "Allianz",
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
                "content-type": "application/json",
                "origin": BASE_URL,
                "referer": SEARCH_URL,
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
        )

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()
        page = 0

        while True:
            payload = dict(PAYLOAD)
            payload["from"] = page * PAYLOAD["size"]

            response = await request.post(API_URL, data=payload)
            print(f"[page {page}] Status: {response.status}  from={payload['from']}")

            if not response.ok:
                raise RuntimeError(
                    f"Allianz API request failed with status {response.status}"
                )

            text = await response.text()
            if page == 0:
                print("--- First API response preview ---")
                print(text[:1500])

            data = json.loads(text)
            raw_jobs = find_job_list(data)

            new_this_page = 0
            for raw in raw_jobs:
                job = normalize_job(raw)
                jid = job.get("job_id") or job.get("url")
                if jid and jid in seen_ids:
                    continue
                if jid:
                    seen_ids.add(jid)
                all_jobs.append(job)
                new_this_page += 1

            print(f"[page {page}] received {len(raw_jobs)} jobs, {new_this_page} new")

            if not raw_jobs or new_this_page == 0:
                break
            if len(raw_jobs) < PAYLOAD["size"]:
                break

            page += 1
            if page > 20:  # safety cap
                break

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=2, ensure_ascii=False)

        print(f"\nSaved {len(all_jobs)} normalized jobs to {OUTPUT_FILE}")

        await request.dispose()


if __name__ == "__main__":
    asyncio.run(main())
