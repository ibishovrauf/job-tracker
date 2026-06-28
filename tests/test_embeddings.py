"""Tests for the embeddings sidecar module (no torch required)."""

from __future__ import annotations

import pytest

from app.embeddings.clean import clean_title_for_embedding


class TestCleanTitle:
    """Test deterministic title cleaning before embedding."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Werkstudent Data Science (m/w/d)", "data science"),
            ("Praktikant:in Machine Learning", "machine learning"),
            ("Intern - AI Engineering (f/m/d)", "ai engineering"),
            ("Working Student - Cloud DevOps (all genders)", "cloud devops"),
            ("Masterand Computer Vision (w/m/div.)", "computer vision"),
            ("Pflichtpraktikum NLP & LLM Ops", "nlp & llm ops"),
            ("Bachelorarbeit Deep Learning", "deep learning"),
            ("Software Engineer", "software engineer"),
            # Edge: only role tokens → empty
            ("Praktikant (m/w/d)", ""),
            ("Werkstudent (f/m/d)", ""),
            ("Intern", ""),
            # Edge: empty input
            ("", ""),
            ("   ", ""),
            # Multiple role tokens
            ("Werkstudent / Praktikant Data Analytics (m/w/d)", "data analytics"),
            # Gender suffix variations
            ("Data Scientist (gn*)", "data scientist"),
        ],
    )
    def test_clean_title(self, raw: str, expected: str) -> None:
        assert clean_title_for_embedding(raw) == expected

    def test_idempotent(self) -> None:
        """Cleaning an already-cleaned title returns the same result."""
        cleaned = clean_title_for_embedding("Werkstudent AI (m/w/d)")
        assert clean_title_for_embedding(cleaned) == cleaned
