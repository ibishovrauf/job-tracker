import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from playwright.async_api import async_playwright

BASE_URL = "https://mercedes-benz-beesite-production-gjb.app.beesite.de"
SEARCH_ENDPOINT = f"{BASE_URL}/search"

OUTPUT_FILE = "mercedes_benz_beesite_jobs.json"
RAW_DEBUG_FILE = "mercedes_benz_beesite_raw_debug.json"

KEYWORDS = [
    "intern",
    "internship",
    "praktikant",
    "werkstudent",
    "working student",
]

COUNT_ITEM = 300
MAX_PAGES_PER_SEARCH = 100

MATCHED_OBJECT_DESCRIPTORS = [
    "ID",
    "CareerLevel.Name",
    "PositionID",
    "PositionTitle",
    "PositionURI",
    "OrganizationName",
    "PositionLocation.CityName",
    "PositionLocation.DisplayName",
    "PositionLocation.CountryCode",
    "PositionLocation.Country",
    "PositionLocation.Latitude",
    "PositionLocation.Longitude",
    "ParentOrganization",
    "ParentOrganizationName",
    "PositionStartDate",
    "PositionFormattedDescription.Content",
    "UserAreaParentOrganizationIdentifier",
    "PositionIndustry.Name",
    "JobCategory.Name",
    "CareerLevel.Name",
    "PositionOfferingType.Name",
    "PublicationStartDate",
    "PositionSchedule.Name",
    "LogoURI",
    "ApplyURI",
    "PositionURL.EmbedURL",
    "PositionURL.URL",
    "PositionURL.ChannelId",
]


def build_keyword_criteria(keyword: str) -> list[dict]:
    return [
        {
            "CriterionName": "PublicationLanguage.Code",
            "CriterionValue": ["EN"],
        },
        {
            "CriterionName": "PositionFormattedDescription.Content",
            "CriterionValue": [keyword],
        },
    ]


def build_career_level_criteria() -> list[dict]:
    return [
        {
            "CriterionName": "PublicationLanguage.Code",
            "CriterionValue": ["EN"],
        },
        {
            "CriterionName": "CareerLevel.Code",
            "CriterionValue": [19],
        },
    ]


def build_payload(first_item: int, count_item: int, criteria: list[dict]) -> dict:
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
        "SearchCriteria": criteria,
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


def get_nested(data: Any, path: str) -> Any:
    if not isinstance(data, dict):
        return None

    if path in data:
        return data[path]

    current = data

    for part in path.split("."):
        if not isinstance(current, dict):
            return None

        current = current.get(part)

    return current


def descriptor_list_to_dict(value: Any) -> dict:
    output = {}

    if isinstance(value, dict):
        return value

    if not isinstance(value, list):
        return output

    for item in value:
        if not isinstance(item, dict):
            continue

        key = (
            item.get("Name")
            or item.get("DescriptorName")
            or item.get("CriterionName")
            or item.get("Key")
            or item.get("FieldName")
        )

        if "Value" in item:
            val = item.get("Value")
        elif "DescriptorValue" in item:
            val = item.get("DescriptorValue")
        elif "CriterionValue" in item:
            val = item.get("CriterionValue")
        elif "Text" in item:
            val = item.get("Text")
        elif "Content" in item:
            val = item.get("Content")
        else:
            val = None

        if key:
            output[key] = val

    return output


def normalize_item(item: dict) -> dict:
    normalized = {}

    if isinstance(item, dict):
        normalized.update(item)

    descriptor = (
        item.get("MatchedObjectDescriptor")
        or item.get("MatchedObjectDescriptors")
        or item.get("Descriptor")
        or item.get("Descriptors")
    )

    normalized.update(descriptor_list_to_dict(descriptor))

    return normalized


def recursively_find_items(data: Any) -> list[dict]:
    if isinstance(data, dict):
        for key in [
            "SearchResultItems",
            "searchResultItems",
            "Results",
            "results",
            "Items",
            "items",
            "MatchedObjects",
            "matchedObjects",
        ]:
            value = data.get(key)

            if isinstance(value, list) and value:
                if all(isinstance(item, dict) for item in value):
                    return value

        for value in data.values():
            found = recursively_find_items(value)

            if found:
                return found

    if isinstance(data, list):
        if data and all(isinstance(item, dict) for item in data):
            text = json.dumps(data[:3], ensure_ascii=False)

            if "PositionTitle" in text or "MatchedObjectDescriptor" in text or "PositionID" in text:
                return data

        for value in data:
            found = recursively_find_items(value)

            if found:
                return found

    return []


def recursively_find_total(data: Any) -> int | None:
    total_keys = {
        "SearchResultCount",
        "searchResultCount",
        "TotalCount",
        "totalCount",
        "Total",
        "total",
        "Count",
        "count",
        "NumberOfResults",
        "numberOfResults",
    }

    if isinstance(data, dict):
        for key, value in data.items():
            if key in total_keys:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass

        for value in data.values():
            found = recursively_find_total(value)

            if found is not None:
                return found

    if isinstance(data, list):
        for value in data:
            found = recursively_find_total(value)

            if found is not None:
                return found

    return None


def extract_value(data: dict, field: str) -> str:
    value = get_nested(data, field)

    if value is None:
        value = data.get(field)

    if value is None:
        value = data.get(field.replace(".", "_"))

    return clean_text(value)


def make_absolute_url(value: str) -> str:
    if not value:
        return ""

    if value.startswith("http"):
        return value

    return urljoin(BASE_URL, value)


def parse_jobs(data: dict, search_name: str) -> tuple[list[dict], int | None]:
    items = recursively_find_items(data)
    total = recursively_find_total(data)

    jobs = []
    seen_local = set()

    for item in items:
        normalized = normalize_item(item)

        job_id = (
            extract_value(normalized, "PositionID")
            or extract_value(normalized, "ID")
            or extract_value(normalized, "PositionURI")
        )

        title = extract_value(normalized, "PositionTitle")

        if not job_id and not title:
            continue

        url = (
            extract_value(normalized, "PositionURL.URL")
            or extract_value(normalized, "PositionURL.EmbedURL")
            or extract_value(normalized, "PositionURI")
        )

        dedupe_key = job_id or url or title

        if dedupe_key in seen_local:
            continue

        seen_local.add(dedupe_key)

        jobs.append(
            {
                "company": "Mercedes-Benz",
                "matched_search": search_name,
                "job_id": job_id,
                "position_id": extract_value(normalized, "PositionID"),
                "title": title,
                "organization": extract_value(normalized, "OrganizationName"),
                "parent_organization": extract_value(normalized, "ParentOrganizationName"),
                "city": extract_value(normalized, "PositionLocation.CityName"),
                "location": extract_value(normalized, "PositionLocation.DisplayName"),
                "country_code": extract_value(normalized, "PositionLocation.CountryCode"),
                "country": extract_value(normalized, "PositionLocation.Country"),
                "career_level": extract_value(normalized, "CareerLevel.Name"),
                "job_category": extract_value(normalized, "JobCategory.Name"),
                "industry": extract_value(normalized, "PositionIndustry.Name"),
                "offering_type": extract_value(normalized, "PositionOfferingType.Name"),
                "schedule": extract_value(normalized, "PositionSchedule.Name"),
                "published_on": extract_value(normalized, "PublicationStartDate"),
                "start_date": extract_value(normalized, "PositionStartDate"),
                "apply_url": make_absolute_url(extract_value(normalized, "ApplyURI")),
                "url": make_absolute_url(url),
                "description": extract_value(
                    normalized,
                    "PositionFormattedDescription.Content",
                ),
            }
        )

    return jobs, total


async def fetch_json(request_context, payload: dict) -> dict:
    url = build_search_url(payload)

    response = await request_context.get(
        url,
        timeout=120_000,
        headers={
            "accept": "application/json, text/plain, */*",
            "referer": "https://jobs.mercedes-benz.com/",
        },
    )

    if not response.ok:
        raise RuntimeError(f"Mercedes-Benz Beesite request failed: HTTP {response.status}")

    text = await response.text()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        Path(RAW_DEBUG_FILE).write_text(text, encoding="utf-8")
        raise RuntimeError(f"Response was not valid JSON. Raw response saved to {RAW_DEBUG_FILE}")


async def scrape_search(
    request_context,
    search_name: str,
    criteria: list[dict],
) -> list[dict]:
    all_jobs = []
    seen_keys = set()

    first_item = 1

    for page_index in range(MAX_PAGES_PER_SEARCH):
        print(f"Mercedes-Benz search={search_name!r}, page={page_index + 1}")

        payload = build_payload(
            first_item=first_item,
            count_item=COUNT_ITEM,
            criteria=criteria,
        )

        data = await fetch_json(request_context, payload)

        if page_index == 0:
            Path(RAW_DEBUG_FILE).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        page_jobs, total = parse_jobs(data, search_name)

        if not page_jobs:
            break

        new_count = 0

        for job in page_jobs:
            dedupe_key = job["job_id"] or job["url"] or job["title"]

            if dedupe_key in seen_keys:
                continue

            seen_keys.add(dedupe_key)
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

    return all_jobs


def build_searches() -> list[dict]:
    searches = []

    for keyword in KEYWORDS:
        searches.append(
            {
                "name": f"keyword:{keyword}",
                "criteria": build_keyword_criteria(keyword),
            }
        )

    searches.append(
        {
            "name": "career_level_code:19",
            "criteria": build_career_level_criteria(),
        }
    )

    return searches


async def main():
    all_jobs = []
    seen_global = set()

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
            for search in build_searches():
                search_jobs = await scrape_search(
                    request_context=request_context,
                    search_name=search["name"],
                    criteria=search["criteria"],
                )

                added = 0

                for job in search_jobs:
                    dedupe_key = job["job_id"] or job["url"] or job["title"]

                    if dedupe_key in seen_global:
                        continue

                    seen_global.add(dedupe_key)
                    all_jobs.append(job)
                    added += 1

                print(f"Added unique from {search['name']}: {added}")

        finally:
            await request_context.dispose()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(all_jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
