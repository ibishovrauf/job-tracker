from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models import Job, StatusEvent  # noqa: F401 — ensure tables are registered


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def settings():
    return Settings(
        keywords=["Werkstudent", "Praktikum"],
        location="",
        published_within_days=7,
        database_url="sqlite://",
        sources={"arbeitsagentur": True, "arbeitnow": True, "adzuna": False, "ats": False},
    )


BA_SAMPLE_RESPONSE = {
    "stellenangebote": [
        {
            "refnr": "10000-1234567890-S",
            "titel": "Werkstudent Software Engineering (m/w/d)",
            "arbeitgeber": "Tech GmbH",
            "arbeitsort": {"ort": "Berlin", "region": "Berlin", "plz": "10115"},
            "aktuelleVeroeffentlichungsdatum": "2025-01-15",
        },
        {
            "refnr": "10000-9876543210-S",
            "titel": "Praktikum Data Science",
            "arbeitgeber": "Data AG",
            "arbeitsort": {"ort": "München", "region": "Bayern"},
            "aktuelleVeroeffentlichungsdatum": "2025-01-14",
            "externeUrl": "https://example.com/apply",
        },
    ]
}

ARBEITNOW_SAMPLE_RESPONSE = {
    "data": [
        {
            "slug": "werkstudent-backend-123",
            "title": "Werkstudent Backend Developer",
            "company_name": "Startup SE",
            "location": "Berlin, Germany",
            "url": "https://www.arbeitnow.com/view/werkstudent-backend-123",
            "tags": ["python", "django"],
            "job_types": ["part time"],
            "created_at": 9999999999,
            "description": "Looking for a Werkstudent ...",
            "remote": True,
        },
        {
            "slug": "senior-manager-456",
            "title": "Senior Manager",
            "company_name": "Big Corp",
            "location": "Hamburg",
            "url": "https://www.arbeitnow.com/view/senior-manager-456",
            "tags": [],
            "job_types": ["full time"],
            "created_at": 9999999999,
            "description": "A senior position with no matching keywords",
            "remote": False,
        },
    ]
}
