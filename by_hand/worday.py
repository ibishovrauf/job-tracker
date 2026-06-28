import asyncio
import json
from urllib.parse import urljoin

from playwright.async_api import async_playwright

KEYWORDS = [
    "intern",
    "internship",
    "praktikant",
    "werkstudent",
    "working student",
]

SITES = [
    {
        "company": "ZEISS",
        "host": "https://zeissgroup.wd3.myworkdayjobs.com",
        "tenant": "zeissgroup",
        "site": "External",
        "keywords": KEYWORDS,
        "facets": {
            "locationCountry": ["dcc5b7608d8644b3a93716604e78e995"],
        },
    },
    {
        "company": "Philips",
        "host": "https://philips.wd3.myworkdayjobs.com",
        "tenant": "philips",
        "site": "jobs-and-careers",
        "keywords": KEYWORDS,
        "facets": {
            "locationHierarchy1": ["6e1b2a934716103c2addbef8087f00d6"],
        },
    },
    {
        "company": "Mercedes-Benz Tech Innovation",
        "host": "https://mercedesbenztechinnovation.wd3.myworkdayjobs.com",
        "tenant": "mercedesbenztechinnovation",
        "site": "MBTI_JOBPORTAL",
        "keywords": [""],
        "facets": {
            "workerSubType": [
                "484c65b37bd4018ec01c51895921eb09",
                "484c65b37bd401f214ae66895921f109",
            ],
        },
    },
    {
        "company": "nvidia",
        "host": "https://nvidia.wd5.myworkdayjobs.com",
        "tenant": "nvidia",
        "site": "NVIDIAExternalCareerSite",
        "keywords": KEYWORDS,
        "facets": {"locationHierarchy1": ["2fcb99c455831013ea52adc65f5d3254"]},
    },
    {
        "company": "accenture",
        "host": "https://accenture.wd103.myworkdayjobs.com",
        "tenant": "accenture",
        "site": "AccentureCareers",
        "keywords": KEYWORDS,
        "facets": {"locationCountry": ["dcc5b7608d8644b3a93716604e78e995"]},
    },
    {
        "company": "intel",
        "host": "https://intel.wd1.myworkdayjobs.com",
        "tenant": "intel",
        "site": "External",
        "keywords": KEYWORDS,
        "facets": {
            "locations": ["1e4a4eb3adf101311d06d076bf815ccf"],
        },
    },
    {
        "company": "trumpf",
        "host": "https://trumpf.wd3.myworkdayjobs.com",
        "tenant": "trumpf",
        "site": "TRUMPF_Students",
        "keywords": KEYWORDS,
        "facets": {
            "locationCountry": ["dcc5b7608d8644b3a93716604e78e995"],
        },
    },
    {
        "company": "Airbus",
        "host": "https://ag.wd3.myworkdayjobs.com",
        "tenant": "ag",
        "site": "Airbus",
        "keywords": [""],
        "facets": {
            "locationCountry": ["dcc5b7608d8644b3a93716604e78e995"],
            "workerSubType": ["f5811cef9cb50193723ed01d470a6e15"],
        },
    },
    {
        "company": "Alcon",
        "host": "https://alcon.wd5.myworkdayjobs.com",
        "tenant": "alcon",
        "site": "careers_alcon",
        "keywords": [""],
        "facets": {
            "locationCountry": ["dcc5b7608d8644b3a93716604e78e995"],
            "workerSubType": ["bc20fe7ae82b018f51983e29d7390721"],
        },
    },
]


def build_job_url(host: str, site: str, external_path: str) -> str:
    if external_path.startswith("http"):
        return external_path
    return urljoin(f"{host}/en-US/{site}/", external_path.lstrip("/"))


async def scrape_query(context, cfg, keyword: str):
    api_url = f"{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}/jobs"

    jobs = []
    offset = 0
    limit = 20

    while True:
        payload = {
            "appliedFacets": cfg["facets"],
            "limit": limit,
            "offset": offset,
            "searchText": keyword,
        }

        res = await context.post(
            api_url,
            data=json.dumps(payload),
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "origin": cfg["host"],
                "referer": f"{cfg['host']}/en-US/{cfg['site']}",
            },
        )

        if not res.ok:
            print(f"{cfg['company']} / {keyword!r} failed: HTTP {res.status}")
            break

        data = await res.json()
        postings = data.get("jobPostings", [])

        if not postings:
            break

        for item in postings:
            title = item.get("title", "").strip()
            path = item.get("externalPath", "")

            if not title or not path:
                continue

            jobs.append(
                {
                    "company": cfg["company"],
                    "matched_keyword": keyword,
                    "title": title,
                    "location": item.get("locationsText", ""),
                    "posted_on": item.get("postedOn", ""),
                    "url": build_job_url(cfg["host"], cfg["site"], path),
                }
            )

        total = data.get("total", 0)
        offset += limit

        if offset >= total:
            break

    return jobs


async def main():
    all_jobs = []
    seen_urls = set()

    async with async_playwright() as p:
        context = await p.request.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            )
        )

        for cfg in SITES[::-1]:
            print(f"Scraping {cfg['company']}...")

            for keyword in cfg["keywords"]:
                label = keyword or "facets only"
                print(f"  Search: {label}")

                jobs = await scrape_query(context, cfg, keyword)

                for job in jobs:
                    if job["url"] in seen_urls:
                        continue

                    seen_urls.add(job["url"])
                    all_jobs.append(job)

            print(f"  Total unique so far: {len(all_jobs)}")

        await context.dispose()

    with open("workday_jobs.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(all_jobs)} jobs to workday_jobs.json")


if __name__ == "__main__":
    asyncio.run(main())
