"""Location allow-list filter applied to every source's output."""

from __future__ import annotations

import re
import unicodedata


def _fold(text: str) -> str:
    """Lowercase and strip accents, so "Budaörs" and "Budaors" compare equal.

    Args:
        text: Any string.

    Returns:
        The accent-free, lowercased string.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def compile_location_filter(terms: list[str]) -> re.Pattern[str] | None:
    """Build one whole-word regex from the configured place names.

    Args:
        terms: Place names such as ["Budapest", "Hungary", "Budaörs"].

    Returns:
        A compiled pattern, or None when no terms are configured (no filtering).
    """
    cleaned = [_fold(t).strip() for t in terms if t.strip()]
    if not cleaned:
        return None
    alternation = "|".join(re.escape(t) for t in cleaned)
    return re.compile(rf"\b(?:{alternation})\b")


def matches_location(location: str, pattern: re.Pattern[str] | None) -> bool:
    """Check whether a job's location passes the filter.

    Args:
        location: The job's location string as scraped.
        pattern: Output of compile_location_filter.

    Returns:
        True if there is no filter, or the location mentions an allowed place.
    """
    if pattern is None:
        return True
    return bool(pattern.search(_fold(location or "")))
