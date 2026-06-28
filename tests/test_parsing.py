from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.config import ATSCompany, Settings
from app.scraping.arbeitsagentur import ArbeitsagenturSource
from app.scraping.arbeitnow import ArbeitnowSource
from app.scraping.adzuna import AdzunaSource
from app.scraping.ats import (
    _parse_ashby,
    _parse_greenhouse,
    _parse_lever,
    _parse_personio,
)
from tests.conftest import ARBEITNOW_SAMPLE_RESPONSE, BA_SAMPLE_RESPONSE

ADZUNA_SAMPLE_RESPONSE = {
    "results": [
        {
            "id": "4001234567",
            "title": "Werkstudent Software Development",
            "company": {"display_name": "Adzuna Corp"},
            "location": {"display_name": "Berlin, Germany"},
            "redirect_url": "https://adzuna.de/land/ad/4001234567",
            "created": "2025-01-15T12:00:00Z",
            "description": "Looking for a Werkstudent...",
            "contract_time": "part_time",
        }
    ]
}

GREENHOUSE_SAMPLE = {
    "jobs": [
        {
            "id": 100,
            "title": "Werkstudent Frontend (m/w/d)",
            "location": {"name": "Berlin"},
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/100",
            "updated_at": "2025-01-15",
            "content": "<p>Description</p>",
        }
    ]
}

LEVER_SAMPLE = [
    {
        "id": "abc-200",
        "text": "Praktikum Backend Engineer",
        "categories": {"team": "Engineering", "location": "München", "commitment": "Internship"},
        "hostedUrl": "https://jobs.lever.co/testco/abc-200",
        "createdAt": 1705305600000,
        "descriptionPlain": "Join our team as a Praktikum...",
    }
]

ASHBY_SAMPLE = {
    "name": "Ashby Corp",
    "jobs": [
        {
            "id": "job-300",
            "title": "Working Student Data Science",
            "location": "Hamburg",
            "employmentType": "Part-time",
            "jobUrl": "https://jobs.ashbyhq.com/ashbycorp/job-300",
            "publishedDate": "2025-01-14",
        }
    ],
}

PERSONIO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
  <position>
    <id>400</id>
    <name>Werkstudent HR (m/w/d)</name>
    <office>Frankfurt</office>
    <recruitingCategory>Working Student</recruitingCategory>
    <employmentType>Part-time</employmentType>
  </position>
</workzag-jobs>
"""


class TestArbeitsagenturParsing:
    def test_parse_item_basic(self) -> None:
        source = ArbeitsagenturSource()
        item = BA_SAMPLE_RESPONSE["stellenangebote"][0]
        raw = source._parse_item(item)

        assert raw.source == "arbeitsagentur"
        assert raw.external_id == "10000-1234567890-S"
        assert raw.title == "Werkstudent Software Engineering (m/w/d)"
        assert raw.company == "Tech GmbH"
        assert raw.location == "Berlin, Berlin"
        assert "arbeitsagentur.de" in raw.url
        assert raw.published == "2025-01-15"

    def test_parse_item_external_url(self) -> None:
        source = ArbeitsagenturSource()
        item = BA_SAMPLE_RESPONSE["stellenangebote"][1]
        raw = source._parse_item(item)

        assert raw.url == "https://example.com/apply"
        assert raw.external_id == "10000-9876543210-S"

    def test_fetch_mocked(self, settings) -> None:
        source = ArbeitsagenturSource()

        def mock_get(*args, **kwargs):
            request = httpx.Request("GET", "https://example.com")
            return httpx.Response(200, json=BA_SAMPLE_RESPONSE, request=request)

        with patch("app.scraping.arbeitsagentur.httpx.get", side_effect=mock_get):
            with patch("app.scraping.arbeitsagentur.time.sleep"):
                results = source.fetch(settings)

        assert len(results) >= 2

    def test_fetch_handles_error(self, settings) -> None:
        source = ArbeitsagenturSource()

        def mock_get(*args, **kwargs):
            raise httpx.ConnectError("offline")

        with patch("app.scraping.arbeitsagentur.httpx.get", side_effect=mock_get):
            results = source.fetch(settings)

        assert results == []


class TestArbeitnowParsing:
    def test_parse_item(self) -> None:
        source = ArbeitnowSource()
        item = ARBEITNOW_SAMPLE_RESPONSE["data"][0]
        raw = source._parse_item(item)

        assert raw.source == "arbeitnow"
        assert raw.external_id == "werkstudent-backend-123"
        assert raw.title == "Werkstudent Backend Developer"
        assert raw.company == "Startup SE"
        assert raw.remote is True
        assert "remote" in raw.job_type.lower()

    def test_keyword_filter_match(self) -> None:
        source = ArbeitnowSource()
        item = ARBEITNOW_SAMPLE_RESPONSE["data"][0]
        assert source._matches_keywords(item, ["Werkstudent"])

    def test_keyword_filter_no_match(self) -> None:
        source = ArbeitnowSource()
        item = ARBEITNOW_SAMPLE_RESPONSE["data"][1]
        assert not source._matches_keywords(item, ["Werkstudent", "Praktikum"])

    def test_fetch_filters_by_keyword(self, settings) -> None:
        source = ArbeitnowSource()

        def mock_get(*args, **kwargs):
            request = httpx.Request("GET", "https://example.com")
            return httpx.Response(200, json=ARBEITNOW_SAMPLE_RESPONSE, request=request)

        with patch("app.scraping.arbeitnow.httpx.get", side_effect=mock_get):
            with patch("app.scraping.arbeitnow.time.sleep"):
                results = source.fetch(settings)

        titles = [r.title for r in results]
        assert "Werkstudent Backend Developer" in titles
        assert "Senior Manager" not in titles


class TestAdzunaParsing:
    def test_parse_item(self) -> None:
        source = AdzunaSource()
        item = ADZUNA_SAMPLE_RESPONSE["results"][0]
        raw = source._parse_item(item)

        assert raw.source == "adzuna"
        assert raw.external_id == "4001234567"
        assert raw.title == "Werkstudent Software Development"
        assert raw.company == "Adzuna Corp"
        assert raw.location == "Berlin, Germany"
        assert raw.job_type == "part_time"

    def test_fetch_without_key(self, settings) -> None:
        source = AdzunaSource()
        results = source.fetch(settings)
        assert results == []

    def test_fetch_with_key(self, settings) -> None:
        settings.adzuna.app_id = "test_id"
        settings.adzuna.app_key = "test_key"
        source = AdzunaSource()

        def mock_get(*args, **kwargs):
            request = httpx.Request("GET", "https://example.com")
            return httpx.Response(200, json=ADZUNA_SAMPLE_RESPONSE, request=request)

        with patch("app.scraping.adzuna.httpx.get", side_effect=mock_get):
            with patch("app.scraping.adzuna.time.sleep"):
                results = source.fetch(settings)

        assert len(results) >= 1
        assert results[0].title == "Werkstudent Software Development"


class TestATSParsing:
    def test_greenhouse(self) -> None:
        company = ATSCompany(provider="greenhouse", token="testco", name="Test Co")
        jobs = _parse_greenhouse(GREENHOUSE_SAMPLE, company)
        assert len(jobs) == 1
        assert jobs[0].external_id == "100"
        assert jobs[0].source == "ats:greenhouse:testco"
        assert jobs[0].company == "Test Co"
        assert "Berlin" in jobs[0].location

    def test_lever(self) -> None:
        company = ATSCompany(provider="lever", token="testco")
        jobs = _parse_lever(LEVER_SAMPLE, company)
        assert len(jobs) == 1
        assert jobs[0].title == "Praktikum Backend Engineer"
        assert jobs[0].source == "ats:lever:testco"
        assert jobs[0].location == "München"

    def test_ashby(self) -> None:
        company = ATSCompany(provider="ashby", token="ashbycorp")
        jobs = _parse_ashby(ASHBY_SAMPLE, company)
        assert len(jobs) == 1
        assert jobs[0].title == "Working Student Data Science"
        assert jobs[0].company == "Ashby Corp"

    def test_personio_xml(self) -> None:
        company = ATSCompany(provider="personio", token="testco", name="Test Co")
        jobs = _parse_personio(PERSONIO_XML, company)
        assert len(jobs) == 1
        assert jobs[0].external_id == "400"
        assert jobs[0].title == "Werkstudent HR (m/w/d)"
        assert jobs[0].location == "Frankfurt"
        assert "personio.de/job/400" in jobs[0].url
