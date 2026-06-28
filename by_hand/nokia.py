"""Nokia jobs via Oracle HCM Cloud Recruiting CE REST API.

Filters: Location = Germany, Flex field "AttributeChar21" = Student/Intern/Trainee.
"""

import asyncio
import json
from typing import Any, Optional
from urllib.parse import urlencode

from playwright.async_api import async_playwright

BASE_URL = "https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com"
API_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
CAREERS_BASE_URL = "https://nokia.eightfold.ai"  # for building human-friendly job URLs (fallback)
OUTPUT_FILE = "nokia_de_student_jobs_first_page.json"

# Germany location ID (from the URL the user provided)
LOCATION_ID_GERMANY = "300000000471601"
PAGE_SIZE = 25  # API max for this endpoint

FACETS = (
    "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;"
    "ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
)
FLEX_FILTER = '"AttributeChar21|Student or Intern or Trainee"'

# Oracle `finder` format: "findReqs;key1=value1,key2=value2,..."
# - First `;` separates the finder name from parameters.
# - Parameters are comma-separated.
# - Semicolons inside a value (e.g. facetsList) must be URL-encoded as %3B.
BASE_FINDER_PARAMS = [
    f"siteNumber=CX_1",
    f"facetsList={FACETS}",
    f"limit={PAGE_SIZE}",
    "lastSelectedFacet=AttributeChar21",
    f"locationId={LOCATION_ID_GERMANY}",
    f"selectedFlexFieldsFacets={FLEX_FILTER}",
    "sortBy=POSTING_DATES_DESC",
]


def build_finder(offset: int) -> str:
    params = list(BASE_FINDER_PARAMS)
    if offset:
        params.append(f"offset={offset}")
    return "findReqs;" + ",".join(params)


def build_request_url(offset: int) -> str:
    qs = urlencode(
        {
            "onlyData": "true",
            "expand": (
                "requisitionList.workLocation,requisitionList.otherWorkLocations,"
                "requisitionList.secondaryLocations,flexFieldsFacet.values,"
                "requisitionList.requisitionFlexFields"
            ),
            "finder": build_finder(offset),
        }
    )
    return f"{BASE_URL}{API_PATH}?{qs}"


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
    elif isinstance(obj, list):
        for item in obj:
            found = first_value(item, keys)
            if found not in (None, "", []):
                return found
    return None


def as_text(value: Any) -> Optional[str]:
    if value in (None, "", []):
        return None
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x not in (None, "")) or None
    if isinstance(value, dict):
        nested = first_value(value, ["label", "name", "value", "text", "Name"])
        return as_text(nested)
    return str(value).strip() or None


def extract_locations(req: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (full_location, city, country)."""
    primary = req.get("PrimaryLocation")
    country = req.get("PrimaryLocationCountry")

    # workLocation is an expanded nested object
    work_loc = req.get("workLocation") or {}
    if isinstance(work_loc, dict):
        items = work_loc.get("items") or []
        if items and isinstance(items, list):
            wl = items[0]
            primary = primary or wl.get("LocationName") or wl.get("WorkLocationName")
            country = country or wl.get("CountryName")

    # Try other_work_locations / secondary_locations
    if not primary:
        for key in ("otherWorkLocations", "secondaryLocations"):
            nested = req.get(key) or {}
            if isinstance(nested, dict):
                items = nested.get("items") or []
                if items:
                    primary = items[0].get("LocationName") or items[0].get("Name")
                    if primary:
                        break

    city = None
    if primary and "," in primary:
        city = primary.split(",")[0].strip()

    return primary, city, country


def normalize_job(req: dict) -> dict:
    job_id = as_text(
        first_value(
            req,
            ["Id", "ReqId", "RequisitionId", "JobId", "id"],
        )
    )

    title = as_text(
        first_value(req, ["Title", "JobTitle", "Name"])
    )

    location, city, country = extract_locations(req)
    country = country or "Germany"

    posted_date = as_text(
        first_value(
            req,
            [
                "PostedDate",
                "PostingDate",
                "PostingStartDate",
                "ExternalPostedStartDate",
                "CreatedOn",
            ],
        )
    )

    category = as_text(
        first_value(
            req,
            ["Category", "JobFamily", "CategoryName", "JobFunction"],
        )
    )

    workplace_type = as_text(
        first_value(
            req,
            ["WorkplaceType", "WorkLocationCategory", "RemoteWorkType"],
        )
    )

    # Build a public job URL. Oracle careers sites usually expose:
    #   https://<careers-host>/job/<id>
    # but Nokia uses Oracle CE under a custom host. The most reliable fallback
    # is to point at Nokia's careers portal search.
    external_url = as_text(
        first_value(req, ["ExternalURL", "JobUrl", "ApplyUrl"])
    )
    if external_url and not external_url.startswith("http"):
        external_url = f"{BASE_URL}{external_url}"

    if not external_url and job_id:
        external_url = (
            f"{BASE_URL}/hcmUI/CandidateExperience/en/sites/CX_1/job/{job_id}"
        )

    return {
        "company": "Nokia",
        "job_id": job_id,
        "title": title,
        "location": location,
        "city": city,
        "country": country,
        "category": category,
        "experience_level": "Student or Intern or Trainee",
        "workplace_type": workplace_type,
        "posted_date": posted_date,
        "url": external_url,
    }


def find_requisition_list(payload: dict) -> tuple[list[dict], int]:
    """Oracle returns: {items: [{requisitionList: [...], TotalJobsCount: N, ...}]}"""
    items = payload.get("items") or []
    if not items:
        return [], 0
    block = items[0]
    reqs = block.get("requisitionList") or []
    total = (
        block.get("TotalJobsCount")
        or block.get("totalJobsCount")
        or len(reqs)
    )
    return reqs, int(total)


async def main() -> None:
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

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()
        offset = 0
        total_known = None

        while True:
            url = build_request_url(offset)
            response = await request.get(url)
            print(f"[offset {offset}] Status: {response.status}")

            if not response.ok:
                text = await response.text()
                print("--- error body ---")
                print(text[:1000])
                raise RuntimeError(
                    f"Nokia API request failed with status {response.status}"
                )

            payload = json.loads(await response.text())
            reqs, total = find_requisition_list(payload)

            if total_known is None:
                total_known = total
                print(f"Total jobs reported: {total}")

            if not reqs:
                break

            new_this_page = 0
            for req in reqs:
                job = normalize_job(req)
                jid = job.get("job_id") or job.get("url")
                if jid and jid in seen_ids:
                    continue
                if jid:
                    seen_ids.add(jid)
                all_jobs.append(job)
                new_this_page += 1

            print(
                f"[offset {offset}] received {len(reqs)} jobs, "
                f"{new_this_page} new, accumulated {len(all_jobs)}"
            )

            if new_this_page == 0:
                break
            if total_known and len(all_jobs) >= total_known:
                break

            offset += PAGE_SIZE
            if offset > 2000:  # safety cap
                break

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=2, ensure_ascii=False)

        print(f"\nSaved {len(all_jobs)} normalized jobs to {OUTPUT_FILE}")

        await request.dispose()


if __name__ == "__main__":
    asyncio.run(main())
