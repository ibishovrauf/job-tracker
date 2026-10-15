"""Tests for the Hungary profile: location filter, title-only matching, Workday provider."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx

from app.config import ATSCompany, Settings
from app.scraping.ats import ATSSource, _fetch_workday_all, _parse_workday_posted
from app.scraping.location import compile_location_filter, matches_location

WORKDAY = ATSCompany(
    provider="workday",
    token="acme",
    host="acme.wd3.myworkdayjobs.com",
    site="Careers",
    name="Acme",
)

WORKDAY_SEARCH = {
    "total": 3,
    "jobPostings": [
        {
            "title": "Finance Intern",
            "externalPath": "/job/Budapest-Hungary/Finance-Intern_R1",
            "locationsText": "Budapest, Hungary",
            "postedOn": "Posted 3 Days Ago",
            "bulletFields": ["R1"],
        },
        {
            "title": "Data Gyakornok",
            "externalPath": "/job/Multi/Data-Gyakornok_R2",
            "locationsText": "2 Locations",
            "postedOn": "Posted Today",
            "bulletFields": ["R2"],
        },
        {
            "title": "Senior Engineer",
            "externalPath": "/job/London/Senior-Engineer_R3",
            "locationsText": "London",
            "postedOn": "Posted 30+ Days Ago",
            "bulletFields": ["R3"],
        },
    ],
}

WORKDAY_DETAIL = {
    "jobPostingInfo": {"location": "Vienna, Austria", "additionalLocations": ["Budaörs, Hungary"]},
}


def _mock_post(*args, **kwargs) -> httpx.Response:
    return httpx.Response(200, json=WORKDAY_SEARCH, request=httpx.Request("POST", args[0]))


def _mock_get(*args, **kwargs) -> httpx.Response:
    return httpx.Response(200, json=WORKDAY_DETAIL, request=httpx.Request("GET", args[0]))


class TestLocationFilter:
    def test_no_terms_means_no_filter(self) -> None:
        assert matches_location("Berlin", compile_location_filter([])) is True

    def test_matches_city(self) -> None:
        pattern = compile_location_filter(["Budapest", "Budaörs"])
        assert matches_location("BU3-Budapest-GTC White House, Vaci ut 47", pattern)
        assert matches_location("Hungary, Budapest", pattern)

    def test_accent_insensitive(self) -> None:
        pattern = compile_location_filter(["Budaörs"])
        assert matches_location("Budaors", pattern)
        assert matches_location("BUDAÖRS, Pest", pattern)

    def test_whole_word_only(self) -> None:
        # "Vác" must not match "Vaci ut" (a Budapest street)
        pattern = compile_location_filter(["Vác"])
        assert not matches_location("Vaci ut 47, Budapest", pattern)

    def test_rejects_other_cities(self) -> None:
        pattern = compile_location_filter(["Budapest", "Hungary"])
        assert not matches_location("London, Greater London", pattern)
        assert not matches_location("", pattern)


class TestWorkday:
    def test_posted_on(self) -> None:
        today = date(2026, 10, 14)
        assert _parse_workday_posted("Posted Today", today) == "2026-10-14"
        assert _parse_workday_posted("Posted Yesterday", today) == "2026-10-13"
        assert _parse_workday_posted("Posted 3 Days Ago", today) == "2026-10-11"
        assert _parse_workday_posted("Posted 30+ Days Ago", today) == "2026-09-14"
        assert _parse_workday_posted("", today) == ""

    def test_fetch_parses_and_expands_multi_location(self) -> None:
        with (
            patch("app.scraping.ats.httpx.post", side_effect=_mock_post),
            patch("app.scraping.ats.httpx.get", side_effect=_mock_get),
        ):
            jobs = _fetch_workday_all(WORKDAY, ["intern"])

        by_id = {j.external_id: j for j in jobs}
        assert set(by_id) == {"R1", "R2", "R3"}
        assert (
            by_id["R1"].url
            == "https://acme.wd3.myworkdayjobs.com/Careers/job/Budapest-Hungary/Finance-Intern_R1"
        )
        assert by_id["R1"].source == "ats:workday:acme"
        assert by_id["R2"].location == "Vienna, Austria; Budaörs, Hungary"

    def test_dedups_across_keywords(self) -> None:
        with (
            patch("app.scraping.ats.httpx.post", side_effect=_mock_post),
            patch("app.scraping.ats.httpx.get", side_effect=_mock_get),
        ):
            jobs = _fetch_workday_all(WORKDAY, ["intern", "gyakornok"])
        assert len(jobs) == 3

    def test_missing_host_returns_empty(self) -> None:
        assert _fetch_workday_all(ATSCompany(provider="workday", token="x"), ["intern"]) == []


class TestATSTitleOnly:
    def test_title_only_keyword_match(self) -> None:
        settings = Settings(
            keywords=["Intern", "Gyakornok"],
            match_title_only=True,
            ats={"companies": [WORKDAY.model_dump()]},
        )
        with (
            patch("app.scraping.ats.httpx.post", side_effect=_mock_post),
            patch("app.scraping.ats.httpx.get", side_effect=_mock_get),
        ):
            jobs = ATSSource().fetch(settings)

        assert sorted(j.title for j in jobs) == ["Data Gyakornok", "Finance Intern"]
