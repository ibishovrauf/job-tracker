from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models import Job, JobStatus
from app.web.server import create_app
import app.db as db_mod


@pytest.fixture()
def filter_client():
    settings = Settings(database_url="sqlite://")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    old = db_mod._engine
    db_mod._engine = engine

    app = create_app(settings)

    with Session(engine) as s:
        jobs = [
            Job(uid="ba:1", source="arbeitsagentur", external_id="1",
                dedup_key="alpha|werkstudent dev|berlin", title="Werkstudent Dev",
                company="Alpha GmbH", location="Berlin", url="https://example.com/1",
                published="2025-01-15", remote=False, job_type="Werkstudent",
                first_seen=datetime(2025, 1, 15)),
            Job(uid="an:2", source="arbeitnow", external_id="2",
                dedup_key="beta|praktikum data|munich", title="Praktikum Data Science",
                company="Beta SE", location="München", url="https://example.com/2",
                published="2025-01-14", remote=True, job_type="Praktikum",
                first_seen=datetime(2025, 1, 14)),
            Job(uid="ba:3", source="arbeitsagentur", external_id="3",
                dedup_key="gamma|intern ml|hamburg", title="Intern ML Engineer",
                company="Gamma AG", location="Hamburg", url="https://example.com/3",
                published="2025-01-13", remote=False, status=JobStatus.ARCHIVED,
                first_seen=datetime(2025, 1, 13)),
        ]
        for j in jobs:
            s.add(j)
        s.commit()

    client = TestClient(app)
    yield client

    db_mod._engine = old


class TestSearchAndFilter:
    def test_search_by_title(self, filter_client) -> None:
        resp = filter_client.get("/jobs?q=Werkstudent")
        assert "Werkstudent Dev" in resp.text
        assert "Praktikum Data" not in resp.text

    def test_search_by_company(self, filter_client) -> None:
        resp = filter_client.get("/jobs?q=Beta")
        assert "Praktikum Data Science" in resp.text
        assert "Werkstudent Dev" not in resp.text

    def test_filter_by_source(self, filter_client) -> None:
        resp = filter_client.get("/jobs?source=arbeitnow")
        assert "Praktikum Data Science" in resp.text
        assert "Werkstudent Dev" not in resp.text

    def test_filter_by_location(self, filter_client) -> None:
        resp = filter_client.get("/jobs?location=Berlin")
        assert "Werkstudent Dev" in resp.text
        assert "Praktikum Data" not in resp.text

    def test_filter_remote_yes(self, filter_client) -> None:
        resp = filter_client.get("/jobs?remote=yes")
        assert "Praktikum Data Science" in resp.text
        assert "Werkstudent Dev" not in resp.text

    def test_filter_remote_no(self, filter_client) -> None:
        resp = filter_client.get("/jobs?remote=no")
        assert "Werkstudent Dev" in resp.text
        assert "Praktikum Data" not in resp.text

    def test_filter_by_job_type(self, filter_client) -> None:
        resp = filter_client.get("/jobs?job_type=Praktikum")
        assert "Praktikum Data Science" in resp.text
        assert "Werkstudent Dev" not in resp.text

    def test_archived_hidden_by_default(self, filter_client) -> None:
        resp = filter_client.get("/jobs")
        assert "Intern ML Engineer" not in resp.text

    def test_archived_visible_with_filter(self, filter_client) -> None:
        resp = filter_client.get("/jobs?status=ARCHIVED")
        assert "Intern ML Engineer" in resp.text

    def test_combined_filters(self, filter_client) -> None:
        resp = filter_client.get("/jobs?q=Werkstudent&source=arbeitsagentur&location=Berlin")
        assert "Werkstudent Dev" in resp.text

    def test_no_results(self, filter_client) -> None:
        resp = filter_client.get("/jobs?q=nonexistent")
        assert "No jobs found" in resp.text
