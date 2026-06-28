#!/usr/bin/env python3
"""
Run all job scrapers, normalize their JSON output, and create one combined file.

Recommended usage from the folder that contains your scraper files:

    uv run run_all_jobs.py

For daily execution, prefer cron or launchd. This script also supports a simple
long-running mode:

    uv run run_all_jobs.py --daemon --daily-at 07:00
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
TODAY = date.today().isoformat()

COMBINED_JSON = BASE_DIR / "all_jobs.json"
COMBINED_DATED_JSON = BASE_DIR / f"all_jobs_{TODAY}.json"
COMBINED_CSV = BASE_DIR / "all_jobs.csv"
RUN_REPORT_JSON = BASE_DIR / "run_report.json"
NORMALIZED_DIR = BASE_DIR / "normalized_outputs"


@dataclass(frozen=True)
class Scraper:
    name: str
    script: str
    output: str


SCRAPERS: list[Scraper] = [
    Scraper("bmw", "bmw.py", "bmw_jobs.json"),
    Scraper("sap", "sap.py", "sap_jobs.json"),
    Scraper("volkswagen", "vw.py", "volkswagen_jobs.json"),
    Scraper("porsche", "porsche.py", "porsche_beesite_jobs.json"),
    Scraper("mercedes", "mercedes.py", "mercedes_benz_beesite_jobs.json"),
    Scraper("siemens", "siemens.py", "siemens_filtered_jobs.json"),
    Scraper("siemens_healthineers", "siemens_med.py", "siemens_healthineers_jobs.json"),
    Scraper("schwarz", "schwartz.py", "schwarz_jobs.json"),
    Scraper("workday", "worday.py", "workday_jobs.json"),
    Scraper("bechtle", "betchle.py", "bechtle_de_student_jobs_first_page.json"),
    Scraper("capgemini", "capgemini.py", "capgemini_de_student_jobs_first_page.json"),
    Scraper("pgcareers", "pgcareers.py", "pgcareers_first_page_jobs.json"),
    Scraper("pwc", "pwc.py", "pwc_de_internship_jobs_first_page.json"),
    Scraper("pcw", "x2l.py", "softgarden_student_jobs_first_page.json"),
    Scraper("allianz", "allianz.py", "allianz_de_student_jobs_first_page.json"),
    Scraper("nokia", "nokia.py", "nokia_de_student_jobs_first_page.json"),
    Scraper("telekom", "telekom.py", "telekom_de_student_jobs.json"),
    Scraper("daimler_truck", "daimler_truck.py", "daimler_truck_de_student_jobs.json"),
]

MISSING_VALUES = {"", "none", "null", "n/a", "na", "-", "--"}
DATE_CANDIDATE_KEYS = [
    "posted_on",
    "published_on",
    "posting_date",
    "postingDate",
    "postedOn",
    "publicationDate",
    "PublicationStartDate",
    "date",
]

CSV_FIELDS = [
    "company",
    "source",
    "job_id",
    "title",
    "location",
    "city",
    "country",
    "posted_on",
    "scraped_on",
    "url",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        parts = [clean_text(item) for item in value]
        return ", ".join(part for part in parts if part)

    if isinstance(value, dict):
        # Keep nested dicts out of normalized scalar fields.
        return ""

    return " ".join(str(value).replace("\xa0", " ").split())


def is_missing(value: Any) -> bool:
    return clean_text(value).lower() in MISSING_VALUES


def find_first_value(job: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        if key in job and not is_missing(job.get(key)):
            return clean_text(job.get(key))
    return ""


def normalize_posted_date(job: dict[str, Any], today: str) -> str:
    value = find_first_value(job, DATE_CANDIDATE_KEYS)
    return value if value else today


def normalize_location(job: dict[str, Any]) -> str:
    location = find_first_value(
        job,
        [
            "location",
            "locations",
            "city",
            "workplace",
            "workLocation",
            "PositionLocation.DisplayName",
        ],
    )

    if location:
        return location

    city = clean_text(job.get("city"))
    country = clean_text(job.get("country"))

    if city and country:
        return f"{city}, {country}"

    return city or country


def normalize_job(job: dict[str, Any], source: str, today: str) -> dict[str, Any]:
    normalized = dict(job)

    normalized["source"] = source
    normalized["scraped_on"] = today
    normalized["posted_on"] = normalize_posted_date(normalized, today)

    if is_missing(normalized.get("company")):
        normalized["company"] = source

    if is_missing(normalized.get("job_id")):
        fallback_id = find_first_value(
            normalized,
            [
                "url_id",
                "position_id",
                "requisition_id",
                "publication_code",
                "id",
            ],
        )
        if fallback_id:
            normalized["job_id"] = fallback_id

    if is_missing(normalized.get("location")):
        location = normalize_location(normalized)
        if location:
            normalized["location"] = location

    return normalized


def dedupe_key(job: dict[str, Any]) -> str:
    company = clean_text(job.get("company")).lower()
    job_id = clean_text(job.get("job_id")).lower()
    url = clean_text(job.get("url")).lower()
    title = clean_text(job.get("title")).lower()
    location = clean_text(job.get("location")).lower()

    if company and job_id:
        return f"company_id::{company}::{job_id}"

    if url:
        return f"url::{url}"

    return f"fallback::{company}::{title}::{location}"


def read_jobs_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        for key in ("jobs", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    raise ValueError(f"Expected list of jobs in {path}")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, jobs: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            writer.writerow({field: clean_text(job.get(field)) for field in CSV_FIELDS})


def run_scraper(scraper: Scraper, *, fail_fast: bool) -> dict[str, Any]:
    script_path = BASE_DIR / scraper.script
    output_path = BASE_DIR / scraper.output

    result: dict[str, Any] = {
        "name": scraper.name,
        "script": str(script_path),
        "output": str(output_path),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "return_code": None,
        "ok": False,
        "jobs_read": 0,
        "error": "",
    }

    if not script_path.exists():
        result["error"] = f"Script not found: {script_path}"
        print(f"[{scraper.name}] {result['error']}")
        if fail_fast:
            raise FileNotFoundError(result["error"])
        return result

    print("=" * 80)
    print(f"Running {scraper.name}: {script_path.name}")
    print("=" * 80)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    started = time.monotonic()

    try:
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        assert process.stdout is not None
        for line in process.stdout:
            print(f"[{scraper.name}] {line}", end="")

        return_code = process.wait()
        result["return_code"] = return_code
        result["duration_seconds"] = round(time.monotonic() - started, 2)

        if return_code != 0:
            result["error"] = f"{scraper.script} exited with code {return_code}"
            print(f"[{scraper.name}] ERROR: {result['error']}")
            if fail_fast:
                raise RuntimeError(result["error"])
            return result

        if not output_path.exists():
            result["error"] = f"Expected output file not found: {output_path}"
            print(f"[{scraper.name}] ERROR: {result['error']}")
            if fail_fast:
                raise FileNotFoundError(result["error"])
            return result

        jobs = read_jobs_json(output_path)
        result["jobs_read"] = len(jobs)
        result["ok"] = True
        print(f"[{scraper.name}] Read {len(jobs)} jobs from {output_path.name}")
        return result

    except Exception as exc:
        result["duration_seconds"] = round(time.monotonic() - started, 2)
        result["error"] = str(exc)
        print(f"[{scraper.name}] ERROR: {exc}")
        if fail_fast:
            raise
        return result


def collect_and_normalize(today: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    NORMALIZED_DIR.mkdir(exist_ok=True)

    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    read_report: list[dict[str, Any]] = []

    for scraper in SCRAPERS:
        output_path = BASE_DIR / scraper.output
        report_item = {
            "name": scraper.name,
            "output": str(output_path),
            "jobs_in_file": 0,
            "jobs_added": 0,
            "error": "",
        }

        try:
            jobs = read_jobs_json(output_path)
            report_item["jobs_in_file"] = len(jobs)
        except Exception as exc:
            report_item["error"] = str(exc)
            read_report.append(report_item)
            continue

        normalized_jobs = [normalize_job(job, scraper.name, today) for job in jobs]

        normalized_output = NORMALIZED_DIR / scraper.output
        write_json(normalized_output, normalized_jobs)

        added = 0
        for job in normalized_jobs:
            key = dedupe_key(job)
            if key in seen:
                continue
            seen.add(key)
            combined.append(job)
            added += 1

        report_item["jobs_added"] = added
        read_report.append(report_item)

    return combined, read_report


def run_all_once(*, fail_fast: bool = False) -> None:
    today = date.today().isoformat()
    run_started_at = datetime.now().isoformat(timespec="seconds")

    run_results = []
    for scraper in SCRAPERS:
        run_results.append(run_scraper(scraper, fail_fast=fail_fast))

    combined_jobs, read_report = collect_and_normalize(today)

    write_json(COMBINED_JSON, combined_jobs)
    write_json(COMBINED_DATED_JSON, combined_jobs)
    write_csv(COMBINED_CSV, combined_jobs)

    report = {
        "started_at": run_started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "scraped_on": today,
        "total_combined_jobs": len(combined_jobs),
        "combined_json": str(COMBINED_JSON),
        "combined_dated_json": str(COMBINED_DATED_JSON),
        "combined_csv": str(COMBINED_CSV),
        "normalized_dir": str(NORMALIZED_DIR),
        "runs": run_results,
        "read_report": read_report,
    }
    write_json(RUN_REPORT_JSON, report)

    print("=" * 80)
    print(f"Done. Combined jobs: {len(combined_jobs)}")
    print(f"JSON: {COMBINED_JSON}")
    print(f"Dated JSON: {COMBINED_DATED_JSON}")
    print(f"CSV: {COMBINED_CSV}")
    print(f"Report: {RUN_REPORT_JSON}")
    print("=" * 80)


def seconds_until_next_run(daily_at: str) -> float:
    try:
        hour_str, minute_str = daily_at.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
    except ValueError as exc:
        raise ValueError("--daily-at must be in HH:MM format, for example 07:00") from exc

    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if target <= now:
        target += timedelta(days=1)

    return (target - now).total_seconds()


def run_daemon(*, daily_at: str, fail_fast: bool) -> None:
    while True:
        run_all_once(fail_fast=fail_fast)
        wait_seconds = seconds_until_next_run(daily_at)
        next_run = datetime.now() + timedelta(seconds=wait_seconds)
        print(f"Next run at {next_run.isoformat(timespec='minutes')}")
        time.sleep(wait_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all job scrapers and combine their outputs.")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Keep this process running and repeat once per day.",
    )
    parser.add_argument(
        "--daily-at",
        default="07:00",
        help="Daily run time for --daemon mode, in HH:MM local time. Default: 07:00.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately if one scraper fails. Default: continue with the rest.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.daemon:
        run_daemon(daily_at=args.daily_at, fail_fast=args.fail_fast)
    else:
        run_all_once(fail_fast=args.fail_fast)


if __name__ == "__main__":
    main()
