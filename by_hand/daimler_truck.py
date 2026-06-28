"""Daimler Truck jobs via their global jobboard search API.

Filters: CareerLevelExternal 9 (Praktikum) + 3 (Werkstudent), Country=Germany.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

API_URL = "https://global-jobboard-api-jobsearch.daimlertruck.com/search/"
OUTPUT_FILE = "daimler_truck_de_student_jobs.json"

SEARCH_CRITERIA = [
    {"CriterionName": "PublicationChannel.Code", "CriterionValue": ["12"]},
    {"CriterionName": "CareerLevelExternal", "CriterionValue": ["9", "3"]},
    {"CriterionName": "PositionLocation.Country", "CriterionValue": ["46"]},
]

PAGE_SIZE = 50
TIMEOUT = 30


def build_params(first_item: int) -> dict[str, str]:
    payload = {
        "SearchParameters": {
            "FirstItem": first_item,
            "CountItem": PAGE_SIZE,
            "MatchedObjectDescriptor": ["Facet:ParentOrganization"],
        },
        "SearchCriteria": SEARCH_CRITERIA,
        "LanguageCode": "EN",
    }
    return {"data": json.dumps(payload)}


def normalize_job(item: dict[str, Any]) -> dict[str, Any]:
    mo = item.get("MatchedObjectDescriptor", {})

    locations = mo.get("PositionLocation") or []
    city = None
    country = "Germany"
    location_parts: list[str] = []
    for loc in locations:
        c = loc.get("CityName")
        if c and c not in location_parts:
            location_parts.append(c)
        if not city:
            city = c
        country = loc.get("CountryName") or country

    location = ", ".join(location_parts) if location_parts else country

    apply_uris = mo.get("ApplyURI") or []
    url = mo.get("PositionURI") or (apply_uris[0] if apply_uris else None)

    categories = mo.get("JobCategory") or []
    category = ", ".join(c.get("Name", "") for c in categories if c.get("Name"))

    career_levels = mo.get("CareerLevel") or []
    if career_levels and isinstance(career_levels[0], dict):
        experience = ", ".join(c.get("Name", "") for c in career_levels if c.get("Name"))
    else:
        experience = None

    pub_start = None
    channels = mo.get("PublicationChannel") or []
    if channels:
        pub_start = channels[0].get("StartDate")

    return {
        "company": mo.get("ParentOrganizationName") or "Daimler Truck",
        "job_id": mo.get("PositionID") or mo.get("ID"),
        "title": mo.get("PositionTitle"),
        "location": location,
        "city": city,
        "country": country,
        "category": category or None,
        "experience_level": experience,
        "posted_date": pub_start,
        "url": url,
    }


def main() -> None:
    all_jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    first_item = 1
    total_known: int | None = None

    while True:
        params = build_params(first_item)
        print(f"[offset {first_item}] Fetching...")
        resp = httpx.get(API_URL, params=params, timeout=TIMEOUT)
        print(f"[offset {first_item}] Status: {resp.status_code}")

        if not resp.is_success:
            raise RuntimeError(f"Daimler Truck API failed with status {resp.status_code}")

        data = resp.json()
        result = data.get("SearchResult", {})
        items = result.get("SearchResultItems") or []

        if total_known is None:
            total_known = result.get("SearchResultCountAll", 0)
            print(f"Total jobs reported: {total_known}")

        if not items:
            break

        new_this_page = 0
        for item in items:
            job = normalize_job(item)
            jid = job.get("job_id")
            if jid and jid in seen_ids:
                continue
            if jid:
                seen_ids.add(jid)
            all_jobs.append(job)
            new_this_page += 1

        print(f"[offset {first_item}] {len(items)} items, {new_this_page} new, total {len(all_jobs)}")

        first_item += len(items)
        if total_known and first_item > total_known:
            break
        if first_item > 2000:
            break

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(all_jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
