from __future__ import annotations

import typer

from app.config import load_settings_or_exit
from app.db import init_db

app = typer.Typer(help="Budapest internship / student-job vacancy tracker")


@app.command()
def scrape(
    config: str = typer.Option("config.yaml", help="Path to config file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch and report but write nothing"),
) -> None:
    """Fetch latest vacancies from all enabled sources."""
    settings = load_settings_or_exit(config)
    init_db(settings.database_url)

    from app.scraping.pipeline import run_pipeline

    stats = run_pipeline(settings, dry_run=dry_run)
    prefix = "[DRY RUN] " if dry_run else ""
    typer.echo(
        f"{prefix}{stats['new']} new of {stats['fetched']} fetched "
        f"({stats['dedup_skipped']} cross-source duplicates skipped)"
    )


@app.command()
def scrape_portals(
    config: str = typer.Option("config.yaml", help="Path to config file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch and report but write nothing"),
) -> None:
    """Scrape career portals of big companies using Playwright."""
    settings = load_settings_or_exit(config)
    init_db(settings.database_url)

    # Disable all sources except portals
    settings.sources.arbeitsagentur = False
    settings.sources.arbeitnow = False
    settings.sources.adzuna = False
    settings.sources.ats = False
    settings.sources.portals = True

    from app.scraping.pipeline import run_pipeline

    stats = run_pipeline(settings, dry_run=dry_run)
    prefix = "[DRY RUN] " if dry_run else ""
    typer.echo(
        f"{prefix}{stats['new']} new of {stats['fetched']} fetched "
        f"({stats['dedup_skipped']} cross-source duplicates skipped)"
    )


@app.command()
def scrape_byhand(
    config: str = typer.Option("config.yaml", help="Path to config file"),
    run_scripts: bool = typer.Option(
        False, "--run-scripts",
        help="Run the by_hand/*.py scrapers first to refresh all_jobs.json"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch and report but write nothing"),
) -> None:
    """Ingest jobs from by_hand/all_jobs.json (custom hand-written scrapers).

    With --run-scripts, first runs `python by_hand/run_all_jobs.py` to refresh
    the data, then ingests it into the DB.
    """
    import subprocess
    import sys
    from pathlib import Path

    settings = load_settings_or_exit(config)
    init_db(settings.database_url)

    if run_scripts:
        runner = Path("by_hand/run_all_jobs.py").resolve()
        if not runner.exists():
            typer.echo(f"Error: {runner} not found", err=True)
            raise typer.Exit(1)
        typer.echo("Running by-hand scrapers (this may take a few minutes)...")
        result = subprocess.run(
            [sys.executable, runner.name],
            cwd=str(runner.parent),
        )
        if result.returncode != 0:
            typer.echo(f"By-hand runner exited with code {result.returncode}", err=True)
            raise typer.Exit(result.returncode)

    # Only enable byhand source
    settings.sources.arbeitsagentur = False
    settings.sources.arbeitnow = False
    settings.sources.adzuna = False
    settings.sources.ats = False
    settings.sources.portals = False
    settings.sources.byhand = True

    from app.scraping.pipeline import run_pipeline

    stats = run_pipeline(settings, dry_run=dry_run)
    prefix = "[DRY RUN] " if dry_run else ""
    typer.echo(
        f"{prefix}{stats['new']} new of {stats['fetched']} fetched "
        f"({stats['dedup_skipped']} cross-source duplicates skipped)"
    )


@app.command()
def serve(
    config: str = typer.Option("config.yaml", help="Path to config file"),
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to serve on"),
) -> None:
    """Start the web dashboard."""
    import uvicorn

    settings = load_settings_or_exit(config)
    init_db(settings.database_url)

    from app.web.server import create_app

    web_app = create_app(settings)
    typer.echo(f"Dashboard: http://{host}:{port}")
    uvicorn.run(web_app, host=host, port=port, log_level="info")


@app.command()
def stats(
    config: str = typer.Option("config.yaml", help="Path to config file"),
) -> None:
    """Show a quick summary of tracked jobs."""
    from datetime import datetime

    from sqlmodel import Session, func, select

    settings = load_settings_or_exit(config)
    init_db(settings.database_url)

    from app.db import get_engine
    from app.models import Job

    engine = get_engine(settings.database_url)
    with Session(engine) as session:
        total = session.exec(select(func.count()).select_from(Job)).one()
        today = datetime.utcnow().date()
        added_today = session.exec(
            select(func.count())
            .select_from(Job)
            .where(func.date(Job.first_seen) == str(today))
        ).one()

        status_counts = session.exec(
            select(Job.status, func.count()).group_by(Job.status)
        ).all()

    typer.echo(f"Total jobs: {total}")
    typer.echo(f"Added today: {added_today}")
    if status_counts:
        typer.echo("By status:")
        for status, count in sorted(status_counts, key=lambda x: x[0]):
            typer.echo(f"  {status}: {count}")


@app.command()
def embed_refresh(
    config: str = typer.Option("config.yaml", help="Path to config file"),
    force: bool = typer.Option(False, "--force", help="Re-embed all jobs, even if already cached"),
    batch_size: int = typer.Option(256, "--batch-size", help="Encoder batch size"),
) -> None:
    """Encode job titles into vectors for the /matches tab.

    Idempotent: only embeds jobs that don't yet have a JobEmbedding row
    (unless --force is passed).
    """
    import time

    from sqlmodel import Session, select

    from app.embeddings import is_enabled

    if not is_enabled():
        typer.echo(
            "Error: embeddings extra not installed.\n"
            'Run: uv pip install -e ".[embeddings]"',
            err=True,
        )
        raise typer.Exit(1)

    from app.embeddings.clean import clean_title_for_embedding
    from app.embeddings.encoder import MODEL_NAME, encode, get_device

    settings = load_settings_or_exit(config)
    init_db(settings.database_url)

    from app.db import get_engine
    from app.models import Job, JobEmbedding

    engine = get_engine(settings.database_url)

    with Session(engine) as session:
        if force:
            all_jobs = list(session.exec(select(Job)).all())
        else:
            # Only jobs without an existing embedding.
            already = set(
                session.exec(select(JobEmbedding.job_uid)).all()
            )
            all_jobs = [
                j for j in session.exec(select(Job)).all()
                if j.uid not in already
            ]

        typer.echo(f"Jobs to process: {len(all_jobs)}")
        if not all_jobs:
            typer.echo("Nothing to embed.")
            raise typer.Exit(0)

        # Clean titles and filter out empties.
        cleaned: list[tuple[Job, str]] = []
        skipped = 0
        for job in all_jobs:
            ct = clean_title_for_embedding(job.title)
            if ct:
                cleaned.append((job, ct))
            else:
                skipped += 1

        typer.echo(f"Cleaned titles: {len(cleaned)} ({skipped} skipped — empty after cleaning)")

        if not cleaned:
            typer.echo("No titles to embed.")
            raise typer.Exit(0)

        device = get_device()
        typer.echo(f"Using device: {device}")
        typer.echo(f"Model: {MODEL_NAME}")

        texts = [ct for _, ct in cleaned]
        t0 = time.perf_counter()
        vectors = encode(texts, batch_size=batch_size, show_progress=True)
        elapsed = time.perf_counter() - t0

        typer.echo(f"Encoded {len(texts)} titles in {elapsed:.1f}s")

        # Upsert embeddings.
        from datetime import datetime

        now = datetime.utcnow()
        for i, (job, _) in enumerate(cleaned):
            vec_bytes = vectors[i].tobytes()
            existing = session.get(JobEmbedding, job.uid)
            if existing:
                existing.vector = vec_bytes
                existing.model = MODEL_NAME
                existing.created_at = now
                session.add(existing)
            else:
                emb = JobEmbedding(
                    job_uid=job.uid,
                    vector=vec_bytes,
                    model=MODEL_NAME,
                    created_at=now,
                )
                session.add(emb)

            if (i + 1) % 1000 == 0:
                session.commit()

        session.commit()
        typer.echo(
            f"Done. Embedded {len(cleaned)} / {len(all_jobs)} jobs "
            f"({skipped} skipped — empty cleaned title) in {elapsed:.1f}s"
        )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
