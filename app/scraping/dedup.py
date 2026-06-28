from __future__ import annotations

import re


_COMPANY_STRIP = re.compile(r"\b(gmbh|ag|se|kg|co|mbh)\b", re.IGNORECASE)
_GENDER_SUFFIX = re.compile(r"\(m/[wf]/d\)", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = _GENDER_SUFFIX.sub("", text)
    text = _COMPANY_STRIP.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def make_uid(source: str, external_id: str) -> str:
    return f"{source}:{external_id}"


def make_dedup_key(company: str, title: str, location: str) -> str:
    return f"{_normalize(company)}|{_normalize(title)}|{_normalize(location)}"
