"""Offline tests for the enterprise / Hungarian ATS providers in app.scraping.ats_extra."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from app.config import ATSCompany, Settings
from app.scraping import ats_extra as ax


def _resp(payload: dict | str, method: str = "GET") -> httpx.Response:
    request = httpx.Request(method, "https://example.com")
    if isinstance(payload, str):
        return httpx.Response(200, text=payload, request=request)
    return httpx.Response(200, json=payload, request=request)


SETTINGS = Settings()


class TestOracle:
    COMPANY = ATSCompany(
        provider="oracle",
        token="emerson",
        host="x.fa.oraclecloud.com",
        site="CX_1",
        params={"location_id": "1"},
    )
    DATA = {
        "items": [
            {
                "TotalJobsCount": 1,
                "requisitionList": [
                    {
                        "Id": "26011430",
                        "Title": "Technical Pre-Sales Intern",
                        "PrimaryLocation": "Debrecen, Hungary",
                        "PostedDate": "2026-09-25",
                        "secondaryLocations": [{"Name": "BUDAPEST, Hungary"}],
                    }
                ],
            }
        ]
    }

    def test_fetch(self) -> None:
        with patch("app.scraping.ats_extra.httpx.get", return_value=_resp(self.DATA)):
            jobs = ax.fetch_oracle(self.COMPANY, SETTINGS)
        assert len(jobs) == 1
        assert jobs[0].location == "Debrecen, Hungary; BUDAPEST, Hungary"
        assert jobs[0].url.endswith("/sites/CX_1/job/26011430")
        assert jobs[0].published == "2026-09-25"

    def test_missing_param(self) -> None:
        bad = ATSCompany(provider="oracle", token="x", host="h", site="CX_1")
        assert ax.fetch_oracle(bad, SETTINGS) == []


class TestEightfold:
    def test_fetch(self) -> None:
        company = ATSCompany(
            provider="eightfold",
            token="infineon",
            host="jobs.infineon.com",
            params={"domain": "infineon.com", "location": "Hungary"},
        )
        data = {
            "data": {
                "count": 1,
                "positions": [
                    {
                        "id": 5,
                        "displayJobId": "HRC1",
                        "name": "Recruitment Trainee",
                        "standardizedLocations": ["Budapest, HU"],
                        "postedTs": 1790000000,
                        "positionUrl": "/careers/job/5",
                    }
                ],
            }
        }
        with patch("app.scraping.ats_extra.httpx.get", return_value=_resp(data)):
            jobs = ax.fetch_eightfold(company, SETTINGS)
        assert jobs[0].external_id == "HRC1"
        assert jobs[0].url == "https://jobs.infineon.com/careers/job/5"
        assert jobs[0].published.startswith("2026-")


class TestPhenom:
    def test_fetch(self) -> None:
        company = ATSCompany(
            provider="phenom",
            token="pg",
            host="www.pgcareers.com",
            params={
                "lang": "en_global",
                "site_country": "global",
                "page_id": "p",
                "country": "Hungary",
            },
        )
        data = {
            "refineSearch": {
                "totalHits": 1,
                "data": {
                    "jobs": [
                        {
                            "jobId": "R1",
                            "title": "Process Engineer Traineeship",
                            "location": "Csömör, Hungary",
                            "postedDate": "2026-10-01T00:00:00.000+0000",
                        }
                    ]
                },
            }
        }
        with patch("app.scraping.ats_extra.httpx.post", return_value=_resp(data, "POST")):
            jobs = ax.fetch_phenom(company, SETTINGS)
        assert jobs[0].url == "https://www.pgcareers.com/global/en/job/R1"
        assert jobs[0].location == "Csömör, Hungary"
        assert jobs[0].published == "2026-10-01"


class TestTaleo:
    COMPANY = ATSCompany(
        provider="taleo",
        token="mol",
        host="molgroup.taleo.net",
        site="external",
        params={"portal": "1", "location": "2", "lang": "hu"},
    )
    PAGE = {
        "requisitionList": [
            {
                "contestNo": "26002535",
                "column": ["Group Compliance gyakornok", '["Hungary-Budapest"]', "2026.10.15."],
            },
            {
                "contestNo": "26002535",
                "column": ["Group Compliance gyakornok", '["Hungary-Budapest"]', "2026.10.15."],
            },
        ]
    }

    def test_fetch_dedups_and_stops_on_empty_page(self) -> None:
        pages = [_resp(self.PAGE, "POST"), _resp({"requisitionList": []}, "POST")]
        with patch("app.scraping.ats_extra.httpx.post", side_effect=pages):
            jobs = ax.fetch_taleo(self.COMPANY, SETTINGS)
        assert len(jobs) == 1
        assert jobs[0].location == "Hungary-Budapest"
        assert jobs[0].published == "2026-10-15"
        assert jobs[0].url.endswith("jobdetail.ftl?job=26002535&lang=hu")


class TestKarrierportal:
    def test_fetch_tags_address_only_rows_by_county(self) -> None:
        company = ATSCompany(provider="karrierportal", token="mvm")
        row = lambda i, place: {  # noqa: E731
            "id": i,
            "url": f"/allas/x-{i}",
            "row": f'<a class="job_list_title">Job {i}</a><div class="job_list_place">Helyszín: {place}</div>',
        }
        everything = {
            "rows": [
                row(1, "1031 Budapest, Fő utca 1."),
                row(2, "Szentendrei út 207."),
                row(3, "Miskolc"),
            ]
        }
        in_county = {"rows": [row(1, ""), row(2, "")]}
        with patch(
            "app.scraping.ats_extra.httpx.post",
            side_effect=[_resp(everything, "POST"), _resp(in_county, "POST")],
        ):
            jobs = {j.external_id: j for j in ax.fetch_karrierportal(company, SETTINGS)}
        assert jobs["1"].location == "1031 Budapest, Fő utca 1."
        assert jobs["2"].location == "Szentendrei út 207. (Budapest/Pest megye)"
        assert jobs["3"].location == "Miskolc"
        assert jobs["1"].url == "https://mvm.karrierportal.hu/allas/x-1"


class TestHrfelho:
    def test_fetch(self) -> None:
        html = """<div id="job-list"><table><tbody><tr>
            <td><span class="job-title">Trade Marketing Intern</span></td>
            <td data-label="Munkavégzés helye">Budapest</td>
            <td><a class="viewjob" href="/allasajanlat/42/trade-marketing-intern">View</a></td>
        </tr></tbody></table></div>"""
        company = ATSCompany(provider="hrfelho", token="roust")
        with patch("app.scraping.ats_extra.httpx.get", return_value=_resp(html)):
            jobs = ax.fetch_hrfelho(company, SETTINGS)
        assert jobs[0].external_id == "42"
        assert jobs[0].location == "Budapest"
        assert jobs[0].url == "https://roust.hrfelho.hu/allasajanlat/42/trade-marketing-intern"


class TestVeolia:
    def test_fetch(self) -> None:
        html = """<div id="cardContent" totalpages="1"></div>
        <div class="position-card">
          <a class="position-card__header-position" href="/allasok/megtekintes/99">Stratégiai elemző gyakornok</a>
          <a class="position-card__header-location">Budaörs</a>
          <div class="position-card__footer-company">Veolia Energia Magyarország Zrt.</div>
        </div>"""
        company = ATSCompany(provider="veolia_hu", token="veolia")
        with patch("app.scraping.ats_extra.httpx.get", return_value=_resp(html)):
            jobs = ax.fetch_veolia_hu(company, SETTINGS)
        assert jobs[0].external_id == "99"
        assert jobs[0].company == "Veolia Energia Magyarország Zrt."
        assert jobs[0].location == "Budaörs"
