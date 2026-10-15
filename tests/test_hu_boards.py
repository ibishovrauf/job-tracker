"""Offline tests for the Hungarian student-job boards (app.scraping.hu_boards)."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from app.config import Settings
from app.scraping import hu_boards as hb


def _resp(payload: dict | list | str, status: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com")
    if isinstance(payload, str):
        return httpx.Response(status, text=payload, request=request)
    return httpx.Response(status, json=payload, request=request)


def _settings(**boards: bool) -> Settings:
    return Settings(keywords=["Intern", "Gyakornok", "Diákmunka"], hu_boards=boards)


class TestEnglishHeuristic:
    def test_english_ad(self) -> None:
        assert hb._written_in_english(
            "<p>You will support the team with reporting and analysis.</p>"
        )

    def test_hungarian_ad(self) -> None:
        assert not hb._written_in_english("<p>A feladatok és a szükséges angol nyelvtudás</p>")


class TestZyntern:
    def test_filters_type_and_native_hungarian(self) -> None:
        data = {
            "meta": {"last_page": 1},
            "data": [
                {
                    "id": 1,
                    "title": "Finance Intern",
                    "job_type": {"id": 1},
                    "company": {"name": "MS"},
                    "location": "Budapest",
                    "url": "https://zyntern.com/job/1",
                    "publishes": [{"start_at": "2026-10-01 10:00:00"}],
                    "languages": [
                        {
                            "language_id": 160,
                            "language_level": 50,
                            "name": "Angol",
                            "level_name": "B2",
                        }
                    ],
                },
                {
                    "id": 2,
                    "title": "Pénzügyi gyakornok",
                    "job_type": {"id": 1},
                    "company": {"name": "CIB"},
                    "location": "Budapest",
                    "url": "u",
                    "publishes": [{}],
                    "languages": [{"language_id": 215, "language_level": 100, "name": "Magyar"}],
                },
                {
                    "id": 3,
                    "title": "Junior Auditor",
                    "job_type": {"id": 7},
                    "company": {"name": "PwC"},
                    "location": "Budapest",
                    "url": "u",
                    "publishes": [{}],
                    "languages": [],
                },
            ],
        }
        with patch("app.scraping.hu_boards.httpx.get", return_value=_resp(data)):
            jobs = hb.fetch_zyntern(_settings())
        assert [j.external_id for j in jobs] == ["1"]
        assert jobs[0].published == "2026-10-01"
        assert jobs[0].job_type == "Gyakornok"


class TestMads:
    def test_parse_takes_company_from_title_suffix(self) -> None:
        html = """<div class="card"><h3><a href="/munkak/diak/ssc-bsc/cs-intern-eaton-123">
            Customer Service Intern - Eaton</a></h3>
            <a class="tag-blue" href="/diakmunka/budapest">Budapest, 12. kerület</a>
            <span class="work-price">2 833 Ft / óra</span></div>"""
        jobs = hb._parse_mads(html)
        assert jobs[0].external_id == "123"
        assert jobs[0].company == "Eaton"
        assert jobs[0].location == "Budapest, 12. kerület"
        assert jobs[0].url == "https://mads.hu/munkak/diak/ssc-bsc/cs-intern-eaton-123"

    def test_fetch_stops_on_404(self) -> None:
        page1 = '<div class="card"><h3><a href="/munkak/x-1">A - B</a></h3></div>'
        responses = [_resp(page1), _resp("", 404), _resp(page1), _resp(page1)]
        with (
            patch("app.scraping.hu_boards.httpx.get", side_effect=responses),
            patch("app.scraping.hu_boards.time.sleep"),
        ):
            jobs = hb.fetch_mads(_settings())
        assert len(jobs) == 1


class TestProfession:
    def test_skips_sponsored_and_non_student_titles(self) -> None:
        html = """
        <li class="advertisement-result-list-item" data-prof-id="1" data-item-name="HR gyakornok"
            data-item-brand="Fürge Diák"><h2><a href="https://www.profession.hu/allas/hr-1?x=y">HR</a></h2>
            <div id="detailed-job-card-1-details-location">Budapest</div></li>
        <li class="advertisement-result-list-item" data-prof-id="2" data-item-name="Energetikai szakértő"
            data-item-brand="GTC"><h2><a href="https://www.profession.hu/allas/x-2">X</a></h2></li>
        <li class="advertisement-result-list-item" data-prof-id="3" data-item-name="Sales Intern"
            data-link="https://x/sponsored"><h2><a href="https://www.profession.hu/allas/x-3">X</a></h2></li>
        """
        responses = [_resp(html), _resp(""), _resp(""), _resp("")]
        with (
            patch("app.scraping.hu_boards.httpx.get", side_effect=responses),
            patch("app.scraping.hu_boards.time.sleep"),
        ):
            jobs = hb.fetch_profession(_settings())
        assert [j.external_id for j in jobs] == ["1"]
        assert jobs[0].url == "https://www.profession.hu/allas/hr-1"
        assert jobs[0].location == "Budapest"


class TestSource:
    def test_only_enabled_boards_run(self) -> None:
        settings = _settings(
            zyntern=False, minddiak=False, muisz=False, mads=False, schonherz=True, profession=False
        )
        with patch.dict(hb.BOARDS, {"schonherz": lambda s: ["job"], "zyntern": lambda s: ["no"]}):
            assert hb.HuBoardsSource().fetch(settings) == ["job"]

    def test_failing_board_does_not_break_others(self) -> None:
        def boom(s: Settings) -> list:
            raise httpx.ConnectError("offline")

        settings = _settings(
            zyntern=True, minddiak=False, muisz=False, mads=False, schonherz=True, profession=False
        )
        with patch.dict(hb.BOARDS, {"zyntern": boom, "schonherz": lambda s: ["ok"]}):
            assert hb.HuBoardsSource().fetch(settings) == ["ok"]
