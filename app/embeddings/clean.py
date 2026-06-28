"""Deterministic title cleaning before embedding.

Strips gender suffixes, role-type boilerplate (Werkstudent, Praktikant, …),
and collapses whitespace so the encoder only sees the *topical* content of a
job title.  Pure stdlib — no torch dependency.
"""

from __future__ import annotations

import re

# (m/w/d), (f/m/d), (m/f/x), (all genders), (w/m/div.), …
_GENDER_RE = re.compile(
    r"\s*\("
    r"(?:"
    r"(?:[mwfdx]/){1,3}[mwfdx]"  # e.g. m/w/d, f/m/d, m/f/x
    r"|all\s+genders?"
    r"|w/m/div\.?"
    r"|gn\*?"
    r")"
    r"\)\s*",
    re.IGNORECASE,
)

# Standalone role-type tokens that every student job shares.
_ROLE_TOKENS = {
    "werkstudent",
    "werkstudent:in",
    "werkstudentin",
    "working student",
    "praktikant",
    "praktikant:in",
    "praktikantin",
    "praktikum",
    "pflichtpraktikum",
    "pflichtpraktikant",
    "intern",
    "internship",
    "student",
    "trainee",
    "bachelorand",
    "masterand",
    "bachelorarbeit",
    "masterarbeit",
    "abschlussarbeit",
    "thesis",
}

# Pre-compiled pattern: match any of the role tokens as whole words.
_ROLE_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(_ROLE_TOKENS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Common separators that become noise after token removal.
_SEP_RE = re.compile(r"\s*[–—\-|/,;:]\s*")
_WHITESPACE_RE = re.compile(r"\s{2,}")


def clean_title_for_embedding(title: str) -> str:
    """Return a cleaned title suitable for encoding, or empty string if nothing remains.

    Args:
        title: Raw job title from the database.

    Returns:
        Lowercase cleaned string, or ``""`` if nothing meaningful remains.
    """
    text = title.strip()
    if not text:
        return ""

    # Strip gender suffixes first (they can wrap role tokens).
    text = _GENDER_RE.sub(" ", text)

    # Strip role-type tokens.
    text = _ROLE_RE.sub(" ", text)

    # Collapse leftover separators that are now dangling.
    text = _SEP_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()

    # Lowercase for the encoder (MiniLM is case-aware but lowering helps
    # consistency without hurting semantic quality).
    text = text.lower().strip()

    # If only punctuation / whitespace survived, treat as empty.
    if not text or len(text) < 3:
        return ""

    return text
