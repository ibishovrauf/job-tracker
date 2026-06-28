"""Deutsche Telekom jobs via their careers proxy API.

Filters: experience_level=Working student, job_source=apprenticeship.
Pagination via `page` query param.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

API_URL = "https://careers.telekom.com/api/jobs-proxy/search"
OUTPUT_FILE = "telekom_de_student_jobs.json"

PARAMS = {
    "experience_level": "Working student",
    "job_source": "apprenticeship",
}

TIMEOUT = 30


def _nonempty(val: Any) -> Any:
    """Return None for 'None' strings and actual None."""
    if val is None or val == "None":
        return None
    return val


def normalize_job(raw: dict[str, Any]) -> dict[str, Any]:
    city = _nonempty(raw.get("city"))
    country = _nonempty(raw.get("country")) or "Germany"
    location = _nonempty(raw.get("location")) or (f"{city}, {country}" if city else country)

    return {
        "company": _nonempty(raw.get("company")) or "Deutsche Telekom",
        "job_id": raw.get("requisition_id"),
        "title": _nonempty(raw.get("title")) or raw.get("job_title"),
        "location": location,
        "city": city,
        "country": country,
        "category": _nonempty(raw.get("category")),
        "experience_level": _nonempty(raw.get("experience_level")),
        "job_type": _nonempty(raw.get("job_type")),
        "remote": _nonempty(raw.get("remote")),
        "posted_date": _nonempty(raw.get("creation_datetime")),
        "url": raw.get("apply_url"),
    }


def main() -> None:
    all_jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    page = 1

    while True:
        params = {**PARAMS, "page": page}
        print(f"[page {page}] Fetching...")
        resp = httpx.get(API_URL, params=params, timeout=TIMEOUT)
        print(f"[page {page}] Status: {resp.status_code}")

        if not resp.is_success:
            raise RuntimeError(f"Telekom API failed with status {resp.status_code}")

        data = resp.json()

        if data.get("status_code") != 200:
            print(f"API error: {data.get('message')}")
            break

        jobs = data.get("data") or []
        pagination = data.get("pagination_info") or {}

        new_this_page = 0
        for raw in jobs:
            job = normalize_job(raw)
            jid = job.get("job_id")
            if jid and jid in seen_ids:
                continue
            if jid:
                seen_ids.add(jid)
            all_jobs.append(job)
            new_this_page += 1

        print(f"[page {page}] {len(jobs)} jobs, {new_this_page} new, total {len(all_jobs)}")

        next_page = pagination.get("next_page")
        if not next_page or not jobs:
            break

        page = next_page
        if page > 50:
            break

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(all_jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
