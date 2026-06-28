"""Semantic embedding utilities for the /matches tab.

This is a pure sidecar module — it never runs during the scrape pipeline.
All heavy imports (torch, sentence_transformers) are lazy so the rest of the
app stays fast when the ``embeddings`` extra is not installed.
"""

from __future__ import annotations

_ENABLED: bool | None = None


def is_enabled() -> bool:
    """Return True if torch + sentence-transformers are importable."""
    global _ENABLED
    if _ENABLED is None:
        try:
            import sentence_transformers  # noqa: F401
            import torch  # noqa: F401

            _ENABLED = True
        except ImportError:
            _ENABLED = False
    return _ENABLED
