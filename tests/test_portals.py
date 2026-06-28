"""Tests for the career portal scraper."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.scraping.portal_companies import PortalCompany, load_companies


class TestLoadCompanies:
    def test_load_flat_format(self, tmp_path: Path) -> None:
        f = tmp_path / "companies.json"
        f.write_text(json.dumps(["SAP", "Bosch", "BMW"]))
        result = load_companies(str(f))
        # Flat names have no search_url, so they're filtered out (not enabled)
        assert len(result) == 0

    def test_load_structured_format(self, tmp_path: Path) -> None:
        data = [
            {"name": "SAP", "search_url": "https://jobs.sap.com/search", "platform": "successfactors"},
            {"name": "Bosch", "search_url": "https://jobs.bosch.com", "platform": "generic", "enabled": False},
            {"name": "BMW", "search_url": "https://bmw.jobs.com/search", "platform": "workday"},
        ]
        f = tmp_path / "companies.json"
        f.write_text(json.dumps(data))
        result = load_companies(str(f))
        assert len(result) == 2  # Bosch is disabled
        assert result[0].name == "SAP"
        assert result[0].platform == "successfactors"
        assert result[1].name == "BMW"

    def test_load_missing_file(self) -> None:
        result = load_companies("/nonexistent/path.json")
        assert result == []

    def test_mixed_format(self, tmp_path: Path) -> None:
        data = [
            "Plain Company",
            {"name": "Structured Co", "search_url": "https://example.com/jobs", "platform": "generic"},
        ]
        f = tmp_path / "companies.json"
        f.write_text(json.dumps(data))
        result = load_companies(str(f))
        assert len(result) == 1  # Only the one with search_url


class TestPortalCompanyModel:
    def test_defaults(self) -> None:
        c = PortalCompany(name="Test Corp")
        assert c.platform == "generic"
        assert c.enabled is True
        assert c.search_url == ""
        assert c.career_url == ""

    def test_all_fields(self) -> None:
        c = PortalCompany(
            name="SAP", career_url="https://jobs.sap.com",
            search_url="https://jobs.sap.com/search?q=werkstudent",
            platform="successfactors", enabled=True,
        )
        assert c.name == "SAP"
        assert c.platform == "successfactors"


class TestPortalsWebRoute:
    def test_portals_page_returns_200(self) -> None:
        from app.config import Settings
        from app.web.server import create_app
        import app.db as db_mod

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)
        old = db_mod._engine
        db_mod._engine = engine

        settings = Settings(database_url="sqlite://")
        app = create_app(settings)
        client = TestClient(app)

        resp = client.get("/portals")
        assert resp.status_code == 200
        assert "Career Portals" in resp.text

        db_mod._engine = old
