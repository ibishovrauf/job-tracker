"""Brute-force cosine ranking of jobs against the user's APPLIED/SAVED profile.

The profile vector is the mean of L2-normalised APPLIED+SAVED embeddings,
re-normalised.  Ranking is a single matrix–vector dot product (~0.3 ms for
14k jobs × 384 dims).  No FAISS or sqlite-vec needed at this scale.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
from sqlmodel import Session, col, func, select

from app.embeddings.encoder import EMBED_DIM
from app.models import Job, JobEmbedding, JobStatus


def _bytes_to_vec(raw: bytes) -> np.ndarray:
    """Deserialise a stored embedding back to a float32 vector."""
    return np.frombuffer(raw, dtype=np.float32)


def user_profile_vector(session: Session) -> np.ndarray | None:
    """Compute the mean embedding of APPLIED + SAVED jobs.

    Args:
        session: Active SQLModel session.

    Returns:
        L2-normalised profile vector of shape ``(EMBED_DIM,)``, or ``None``
        if no APPLIED/SAVED jobs have embeddings.
    """
    rows = session.exec(
        select(JobEmbedding.vector)
        .join(Job, Job.uid == JobEmbedding.job_uid)
        .where(col(Job.status).in_([JobStatus.APPLIED, JobStatus.SAVED]))
    ).all()

    if not rows:
        return None

    vecs = np.array([_bytes_to_vec(r) for r in rows], dtype=np.float32)  # (N, 384)
    profile = vecs.mean(axis=0)  # (384,)
    norm = np.linalg.norm(profile)
    if norm < 1e-9:
        return None
    return (profile / norm).astype(np.float32)


def rank_jobs(
    session: Session,
    *,
    statuses: Sequence[JobStatus] | None = None,
    min_score: float = 0.0,
    limit: int = 200,
    today_only: bool = False,
) -> list[tuple[Job, float]]:
    """Return jobs ranked by similarity to the user profile.

    Args:
        session: Active SQLModel session.
        statuses: Only include jobs with these statuses. ``None`` means all
            except NOT_RELEVANT and ARCHIVED.
        min_score: Minimum cosine similarity (0–1).
        limit: Max results.
        today_only: If True, only include jobs first seen today.

    Returns:
        List of ``(job, match_pct)`` tuples sorted by descending match %.
        ``match_pct`` is in [0, 100].
    """
    profile = user_profile_vector(session)
    if profile is None:
        return []

    # Build the query for embedded jobs.
    stmt = (
        select(Job, JobEmbedding.vector)
        .join(JobEmbedding, Job.uid == JobEmbedding.job_uid)
    )
    if statuses is not None:
        stmt = stmt.where(col(Job.status).in_(statuses))
    else:
        stmt = stmt.where(Job.status != JobStatus.NOT_RELEVANT)
        stmt = stmt.where(Job.status != JobStatus.ARCHIVED)

    if today_only:
        today_str = date.today().isoformat()
        stmt = stmt.where(func.date(Job.first_seen) == today_str)

    rows = session.exec(stmt).all()
    if not rows:
        return []

    jobs: list[Job] = []
    mat = np.empty((len(rows), EMBED_DIM), dtype=np.float32)
    for i, (job, vec_bytes) in enumerate(rows):
        jobs.append(job)
        mat[i] = _bytes_to_vec(vec_bytes)

    # Cosine similarity = dot product (vectors are already L2-normalised).
    scores = mat @ profile  # (N,)

    # Filter + sort.
    min_cos = min_score / 100.0 if min_score > 1 else min_score
    ranked: list[tuple[Job, float]] = []
    order = np.argsort(-scores)
    for idx in order:
        s = float(scores[idx])
        if s < min_cos:
            break
        ranked.append((jobs[idx], round(s * 100, 1)))
        if len(ranked) >= limit:
            break

    return ranked


def unembedded_count(session: Session) -> int:
    """Count jobs that don't have an embedding yet."""
    from sqlmodel import func

    total_jobs = session.exec(select(func.count()).select_from(Job)).one()
    total_embedded = session.exec(select(func.count()).select_from(JobEmbedding)).one()
    return total_jobs - total_embedded
