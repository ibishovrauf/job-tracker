"""Load and validate portal companies from companies.json."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PortalCompany(BaseModel):
    name: str
    career_url: str = ""
    search_url: str = ""
    platform: str = "generic"  # workday | successfactors | smartrecruiters | generic
    enabled: bool = True


def load_companies(path: str = "companies.json") -> list[PortalCompany]:
    """Load companies from JSON. Supports both flat and structured formats."""
    p = Path(path)
    if not p.exists():
        logger.warning("Companies file not found: %s", path)
        return []

    raw = json.loads(p.read_text())
    companies: list[PortalCompany] = []
    for item in raw:
        if isinstance(item, str):
            companies.append(PortalCompany(name=item))
        else:
            companies.append(PortalCompany(**item))

    enabled = [c for c in companies if c.enabled and c.search_url]
    logger.info(
        "Loaded %d portal companies (%d enabled with URLs)",
        len(companies), len(enabled),
    )
    return enabled
