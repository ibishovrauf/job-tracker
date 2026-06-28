import asyncio
import json
from typing import Any
from urllib.parse import quote, urljoin

from playwright.async_api import async_playwright

BASE_URL = "https://porsche-beesite-production-gjb.app.beesite.de"
SEARCH_ENDPOINT = f"{BASE_URL}/search/"

OUTPUT_FILE = "porsche_beesite_jobs.json"

COUNT_ITEM = 50
MAX_PAGES = 100

MATCHED_OBJECT_DESCRIPTORS = [
    "ID",
    "PositionTitle",
    "PositionURI",
    "PositionShortURI",
    "PositionLocation.CountryName",
    "PositionLocation.CityName",
    "PositionLocation.Longitude",
    "PositionLocation.Latitude",
    "PositionLocation.PostalCode",
    "PositionLocation.StreetName",
    "PositionLocation.BuildingNumber",
    "PositionLocation.Distance",
    "JobCategory.Name",
    "PublicationStartDate",
    "ParentOrganizationName",
    "ParentOrganization",
    "OrganizationShortName",
    "CareerLevel.Name",
    "JobSector.Name",
    "PositionIndustry.Name",
    "PublicationCode",
    "PublicationChannel.Id",
]


def build_criteria() -> list[dict]:
    return [
        {
            "CriterionName": "PublicationChannel.Code",
            "CriterionValue": ["12"],
        },
        {
            "CriterionName": "CareerLevel.Code",
            "CriterionValue": ["4", "5"],
        },
        {
            "CriterionName": "PositionLocation.Country",
            "CriterionValue": ["46"],
        },
    ]


def build_payload(first_item: int, count_item: int) -> dict:
    return {
        "LanguageCode": "EN",
        "SearchParameters": {
            "FirstItem": first_item,
            "CountItem": count_item,
            "Sort": [
                {
                    "Criterion": "PublicationStartDate",
                    "Direction": "DESC",
                }
            ],
            "MatchedObjectDescriptor": MATCHED_OBJECT_DESCRIPTORS,
        },
        "SearchCriteria": build_criteria(),
    }


def build_search_url(payload: dict) -> str:
    encoded = quote(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        safe="",
    )
    return f"{SEARCH_ENDPOINT}?data={encoded}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, list):
        return ", ".join(clean_text(item) for item in value if clean_text(item))

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)

    return " ".join(str(value).split())


def first_list_item(value: Any) -> dict:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first

    if isinstance(value, dict):
        return value

    return {}


def list_names(value: Any) -> str:
    if not isinstance(value, list):
        return clean_text(value)

    names = []

    for item in value:
        if isinstance(item, dict):
            name = item.get("Name")
            if name:
                names.append(clean_text(name))
        else:
            names.append(clean_text(item))

    return ", ".join(name for name in names if name)


def make_absolute_url(value: str) -> str:
    if not value:
        return ""

    if value.startswith("http"):
        return value

    return urljoin(BASE_URL, value)


def parse_jobs(data: dict) -> tuple[list[dict], int | None]:
    search_result = data.get("SearchResult", {})

    total = search_result.get("SearchResultCountAll")
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = None

    items = search_result.get("SearchResultItems", [])

    jobs = []
    seen_ids = set()

    for item in items:
        descriptor = item.get("MatchedObjectDescriptor", {})

        job_id = clean_text(descriptor.get("ID") or item.get("MatchedObjectId"))

        if not job_id or job_id in seen_ids:
            continue

        seen_ids.add(job_id)

        locations = descriptor.get("PositionLocation", [])
        first_location = first_list_item(locations)

        publication_channels = descriptor.get("PublicationChannel", [])

        jobs.append(
            {
                "company": "Porsche",
                "job_id": job_id,
                "title": clean_text(descriptor.get("PositionTitle")),
                "url": make_absolute_url(clean_text(descriptor.get("PositionURI"))),
                "short_url": make_absolute_url(clean_text(descriptor.get("PositionShortURI"))),
                "published_on": clean_text(descriptor.get("PublicationStartDate")),
                "career_level": list_names(descriptor.get("CareerLevel")),
                "job_category": list_names(descriptor.get("JobCategory")),
                "job_sector": list_names(descriptor.get("JobSector")),
                "industry": list_names(descriptor.get("PositionIndustry")),
                "parent_organization": clean_text(descriptor.get("ParentOrganizationName")),
                "parent_organization_id": clean_text(descriptor.get("ParentOrganization")),
                "organization_short_name": clean_text(descriptor.get("OrganizationShortName")),
                "publication_code": clean_text(descriptor.get("PublicationCode")),
                "publication_channel_ids": [
                    clean_text(channel.get("Id"))
                    for channel in publication_channels
                    if isinstance(channel, dict)
                ],
                "city": clean_text(first_location.get("CityName")),
                "country": clean_text(first_location.get("CountryName")),
                "postal_code": clean_text(first_location.get("PostalCode")),
                "street": clean_text(first_location.get("StreetName")),
                "building_number": clean_text(first_location.get("BuildingNumber")),
                "latitude": first_location.get("Latitude"),
                "longitude": first_location.get("Longitude"),
            }
        )

    return jobs, total


async def fetch_json(request_context, first_item: int, count_item: int) -> dict:
    payload = build_payload(
        first_item=first_item,
        count_item=count_item,
    )

    url = build_search_url(payload)

    response = await request_context.get(
        url,
        timeout=120_000,
        headers={
            "accept": "application/json, text/plain, */*",
            "referer": "https://jobs.porsche.com/",
        },
    )

    if not response.ok:
        raise RuntimeError(f"Porsche Beesite request failed: HTTP {response.status}")

    text = await response.text()
    return json.loads(text)


async def scrape_porsche(request_context) -> list[dict]:
    all_jobs = []
    seen_ids = set()

    first_item = 1

    for page_index in range(MAX_PAGES):
        print(f"Scraping Porsche page {page_index + 1}...")

        data = await fetch_json(
            request_context=request_context,
            first_item=first_item,
            count_item=COUNT_ITEM,
        )

        page_jobs, total = parse_jobs(data)

        if not page_jobs:
            break

        new_count = 0

        for job in page_jobs:
            if job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            all_jobs.append(job)
            new_count += 1

        print(f"  Added {new_count} jobs")

        if new_count == 0:
            break

        if total is not None and len(all_jobs) >= total:
            break

        if len(page_jobs) < COUNT_ITEM:
            break

        first_item += COUNT_ITEM

        await asyncio.sleep(0.2)

    return all_jobs


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
            jobs = await scrape_porsche(request_context)
        finally:
            await request_context.dispose()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
