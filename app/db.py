from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

_engine = None


def get_engine(database_url: str = "sqlite:///./jobtracker.sqlite3"):
    global _engine
    if _engine is None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        _engine = create_engine(database_url, connect_args=connect_args)
    return _engine


def init_db(database_url: str = "sqlite:///./jobtracker.sqlite3") -> None:
    """Create all tables if they don't exist."""
    from app.models import Job, StatusEvent  # noqa: F401 — ensure tables registered

    engine = get_engine(database_url)
    SQLModel.metadata.create_all(engine)


def get_session(database_url: str = "sqlite:///./jobtracker.sqlite3") -> Generator[Session]:
    engine = get_engine(database_url)
    with Session(engine) as session:
        yield session


def reset_engine() -> None:
    """Reset the global engine (useful for tests)."""
    global _engine
    _engine = None
