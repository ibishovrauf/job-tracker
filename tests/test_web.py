from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.models import Job, JobStatus, StatusEvent
from app.web.server import create_app
import app.db as db_mod


@pytest.fixture()
def app_client():
    settings = Settings(database_url="sqlite://")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    old = db_mod._engine
    db_mod._engine = engine

    app = create_app(settings)
    client = TestClient(app)
    yield client, engine

    db_mod._engine = old


def _seed_jobs(engine, count: int = 3) -> list[Job]:
    jobs = []
    with Session(engine) as s:
        for i in range(count):
            job = Job(
                uid=f"test:{i}",
                source="arbeitsagentur",
                external_id=str(i),
                dedup_key=f"company|title-{i}|berlin",
                title=f"Werkstudent Test {i}",
                company=f"Company {i}",
                location="Berlin",
                url=f"https://example.com/{i}",
                published="2025-01-15",
                first_seen=datetime(2025, 1, 15, 10, 0, 0),
            )
            s.add(job)
            jobs.append(job)
        s.commit()
    return jobs


class TestDashboardRoutes:
    def test_index_returns_200(self, app_client) -> None:
        client, engine = app_client
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Job Tracker" in resp.text

    def test_index_shows_jobs(self, app_client) -> None:
        client, engine = app_client
        _seed_jobs(engine)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Werkstudent Test 0" in resp.text

    def test_empty_state(self, app_client) -> None:
        client, engine = app_client
        resp = client.get("/")
        assert "No jobs found" in resp.text

    def test_job_rows_fragment(self, app_client) -> None:
        client, engine = app_client
        _seed_jobs(engine)
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert "Werkstudent Test" in resp.text

    def test_job_detail(self, app_client) -> None:
        client, engine = app_client
        _seed_jobs(engine, 1)
        resp = client.get("/jobs/test:0")
        assert resp.status_code == 200
        assert "Company 0" in resp.text


class TestStatusChange:
    def test_change_status(self, app_client) -> None:
        client, engine = app_client
        _seed_jobs(engine, 1)

        resp = client.post("/jobs/test:0/status", data={"new_status": "APPLIED"})
        assert resp.status_code == 200

        with Session(engine) as s:
            job = s.get(Job, "test:0")
            assert job.status == JobStatus.APPLIED
            assert job.status_updated_at is not None

    def test_status_event_created(self, app_client) -> None:
        client, engine = app_client
        _seed_jobs(engine, 1)
        client.post("/jobs/test:0/status", data={"new_status": "SAVED"})

        with Session(engine) as s:
            events = s.exec(select(StatusEvent).where(StatusEvent.job_uid == "test:0")).all()
            assert len(events) == 1
            assert events[0].from_status == "NEW"
            assert events[0].to_status == "SAVED"


class TestNotes:
    def test_update_notes(self, app_client) -> None:
        client, engine = app_client
        _seed_jobs(engine, 1)

        resp = client.post("/jobs/test:0/notes", data={"notes": "sent CV today"})
        assert resp.status_code == 200

        with Session(engine) as s:
            job = s.get(Job, "test:0")
            assert job.notes == "sent CV today"
