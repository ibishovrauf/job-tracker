import enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class JobStatus(str, enum.Enum):
    NEW = "NEW"
    SAVED = "SAVED"
    APPLIED = "APPLIED"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    NOT_RELEVANT = "NOT_RELEVANT"
    ARCHIVED = "ARCHIVED"


class StatusEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_uid: str = Field(foreign_key="job.uid", index=True)
    from_status: Optional[str] = None
    to_status: str
    at: datetime = Field(default_factory=datetime.utcnow)

    job: Optional["Job"] = Relationship(back_populates="status_events")


class Job(SQLModel, table=True):
    uid: str = Field(primary_key=True)
    source: str
    external_id: str
    dedup_key: str = Field(index=True)
    title: str
    company: str
    location: str
    url: str
    published: str = ""
    job_type: str = ""
    tags: str = ""
    description: Optional[str] = None
    remote: bool = False
    status: JobStatus = Field(default=JobStatus.NEW)
    notes: str = ""
    category: str = Field(default="", index=True)
    first_seen: datetime = Field(default_factory=datetime.utcnow, index=True)
    status_updated_at: Optional[datetime] = None

    status_events: list[StatusEvent] = Relationship(back_populates="job")


class JobEmbedding(SQLModel, table=True):
    """Sidecar table: one embedding per job. Kept separate so the Job model is untouched."""

    job_uid: str = Field(primary_key=True, foreign_key="job.uid")
    vector: bytes  # np.float32 L2-normalized, 384 dims = 1536 bytes
    model: str  # e.g. "paraphrase-multilingual-MiniLM-L12-v2"
    created_at: datetime = Field(default_factory=datetime.utcnow)
