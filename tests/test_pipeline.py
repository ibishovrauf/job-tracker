from __future__ import annotations

from unittest.mock import patch

from sqlmodel import Session, select

from app.models import Job
from app.scraping.base import RawJob
from app.scraping.dedup import make_dedup_key, make_uid
from app.scraping.pipeline import run_pipeline


def _make_raw(source: str = "arbeitsagentur", ext_id: str = "ref-1", title: str = "Werkstudent Dev",
              company: str = "Tech GmbH", location: str = "Berlin") -> RawJob:
    return RawJob(
        source=source,
        external_id=ext_id,
        title=title,
        company=company,
        location=location,
        url=f"https://example.com/{ext_id}",
    )


class TestDedup:
    def test_uid_format(self) -> None:
        assert make_uid("arbeitsagentur", "ref-1") == "arbeitsagentur:ref-1"

    def test_dedup_key_normalizes(self) -> None:
        k1 = make_dedup_key("Tech GmbH", "Werkstudent Dev (m/w/d)", "Berlin")
        k2 = make_dedup_key("tech", "werkstudent dev", "berlin")
        assert k1 == k2

    def test_dedup_key_different_companies(self) -> None:
        k1 = make_dedup_key("Alpha", "Dev", "Berlin")
        k2 = make_dedup_key("Beta", "Dev", "Berlin")
        assert k1 != k2


class TestPipeline:
    def test_first_run_inserts(self, engine, settings) -> None:
        raw = [_make_raw()]
        with patch("app.scraping.pipeline.discover"):
            with patch("app.scraping.pipeline._fetch_all", return_value=raw):
                with patch("app.scraping.pipeline.get_engine", return_value=engine):
                    stats = run_pipeline(settings)

        assert stats["fetched"] == 1
        assert stats["new"] == 1
        assert stats["dedup_skipped"] == 0

        with Session(engine) as s:
            jobs = s.exec(select(Job)).all()
            assert len(jobs) == 1
            assert jobs[0].uid == "arbeitsagentur:ref-1"

    def test_second_run_no_duplicates(self, engine, settings) -> None:
        raw = [_make_raw()]
        with patch("app.scraping.pipeline.discover"):
            with patch("app.scraping.pipeline._fetch_all", return_value=raw):
                with patch("app.scraping.pipeline.get_engine", return_value=engine):
                    run_pipeline(settings)
                    stats = run_pipeline(settings)

        assert stats["new"] == 0

        with Session(engine) as s:
            assert len(s.exec(select(Job)).all()) == 1

    def test_cross_source_dedup(self, engine, settings) -> None:
        raw1 = [_make_raw(source="arbeitsagentur", ext_id="ba-1")]
        raw2 = [_make_raw(source="arbeitnow", ext_id="an-1")]

        with patch("app.scraping.pipeline.discover"):
            with patch("app.scraping.pipeline.get_engine", return_value=engine):
                with patch("app.scraping.pipeline._fetch_all", return_value=raw1):
                    run_pipeline(settings)
                with patch("app.scraping.pipeline._fetch_all", return_value=raw2):
                    stats = run_pipeline(settings)

        assert stats["dedup_skipped"] == 1
        assert stats["new"] == 0

        with Session(engine) as s:
            jobs = s.exec(select(Job)).all()
            assert len(jobs) == 1
            assert jobs[0].source == "arbeitsagentur"

    def test_preserves_status_and_notes(self, engine, settings) -> None:
        raw = [_make_raw()]
        with patch("app.scraping.pipeline.discover"):
            with patch("app.scraping.pipeline._fetch_all", return_value=raw):
                with patch("app.scraping.pipeline.get_engine", return_value=engine):
                    run_pipeline(settings)

        with Session(engine) as s:
            job = s.get(Job, "arbeitsagentur:ref-1")
            job.status = "APPLIED"
            job.notes = "sent CV"
            s.add(job)
            s.commit()

        with patch("app.scraping.pipeline.discover"):
            with patch("app.scraping.pipeline._fetch_all", return_value=raw):
                with patch("app.scraping.pipeline.get_engine", return_value=engine):
                    run_pipeline(settings)

        with Session(engine) as s:
            job = s.get(Job, "arbeitsagentur:ref-1")
            assert job.status == "APPLIED"
            assert job.notes == "sent CV"

    def test_dry_run(self, engine, settings) -> None:
        raw = [_make_raw()]
        with patch("app.scraping.pipeline.discover"):
            with patch("app.scraping.pipeline._fetch_all", return_value=raw):
                with patch("app.scraping.pipeline.get_engine", return_value=engine):
                    stats = run_pipeline(settings, dry_run=True)

        assert stats["new"] == 1

        with Session(engine) as s:
            assert len(s.exec(select(Job)).all()) == 0
