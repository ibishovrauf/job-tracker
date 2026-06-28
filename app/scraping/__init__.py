from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Source

REGISTRY: dict[str, type[Source]] = {}


def register(name: str):
    """Decorator to register a source class."""

    def wrapper(cls: type[Source]) -> type[Source]:
        REGISTRY[name] = cls
        return cls

    return wrapper


def discover() -> None:
    """Import all source modules so they self-register."""
    from . import adzuna, arbeitsagentur, arbeitnow, ats, byhand  # noqa: F401

    try:
        from . import portals  # noqa: F401
    except ImportError:
        pass  # playwright not installed — portal source unavailable
