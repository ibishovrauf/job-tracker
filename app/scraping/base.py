from __future__ import annotations

import abc
from dataclasses import dataclass, field

from app.config import Settings


@dataclass
class RawJob:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    url: str
    published: str = ""
    job_type: str = ""
    tags: str = ""
    description: str | None = None
    remote: bool = False


class Source(abc.ABC):
    name: str

    @abc.abstractmethod
    def fetch(self, settings: Settings) -> list[RawJob]:
        ...
