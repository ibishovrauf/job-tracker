from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class AdzunaConfig(BaseModel):
    app_id: str = ""
    app_key: str = ""


class ATSCompany(BaseModel):
    provider: str
    token: str
    name: str | None = None


class ATSConfig(BaseModel):
    companies: list[ATSCompany] = []


class SourcesConfig(BaseModel):
    arbeitsagentur: bool = True
    arbeitnow: bool = True
    adzuna: bool = False
    ats: bool = True
    portals: bool = False
    byhand: bool = True


class Settings(BaseModel):
    keywords: list[str] = [
        "Werkstudent",
        "Werkstudentin",
        "Working Student",
        "Praktikum",
        "Praktikant",
        "Intern",
        "Internship",
    ]
    location: str = ""
    radius_km: int = 50
    published_within_days: int = 2
    database_url: str = "sqlite:///./jobtracker.sqlite3"
    sources: SourcesConfig = SourcesConfig()
    adzuna: AdzunaConfig = AdzunaConfig()
    ats: ATSConfig = ATSConfig()
    portal_companies_path: str = "companies.json"
    byhand_combined_path: str = "by_hand/all_jobs.json"

    @field_validator("keywords", mode="before")
    @classmethod
    def ensure_keywords_list(cls, v: list[str] | str) -> list[str]:
        if isinstance(v, str):
            return [v]
        return v


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load settings from YAML file, with env-var overrides for secrets."""
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    settings = Settings(**data)

    if env_id := os.environ.get("ADZUNA_APP_ID"):
        settings.adzuna.app_id = env_id
    if env_key := os.environ.get("ADZUNA_APP_KEY"):
        settings.adzuna.app_key = env_key

    return settings


def load_settings_or_exit(config_path: str = "config.yaml") -> Settings:
    """Load settings, exiting with a clear message on failure."""
    try:
        return load_settings(config_path)
    except Exception as e:
        print(f"Error loading config from {config_path}: {e}", file=sys.stderr)
        print("Copy config.example.yaml to config.yaml and adjust it.", file=sys.stderr)
        sys.exit(1)
