from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, func, select

from app.config import Settings
from app.db import get_engine
from app.models import Job, JobStatus, StatusEvent

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


import subprocess
import sys
import threading
from dataclasses import dataclass, field

_scrape_lock = threading.Lock()


@dataclass
class ScrapeStatus:
    running: bool = False
    finished: bool = False
    error: str = ""
    stats: str = ""
    started_at: str = ""


_scrape_jobs: dict[str, ScrapeStatus] = {
    "ats": ScrapeStatus(),
    "byhand": ScrapeStatus(),
}


def _run_scrape_background(key: str, cmd: list[str]) -> None:
    status = _scrape_jobs[key]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = result.stdout.strip()
        last_line = output.split("\n")[-1] if output else ""
        if result.returncode != 0:
            status.error = result.stderr.strip() or f"Exit code {result.returncode}"
            status.stats = last_line
        else:
            status.stats = last_line
            status.error = ""
    except subprocess.TimeoutExpired:
        status.error = "Timed out after 10 minutes"
    except Exception as e:
        status.error = str(e)
    finally:
        status.running = False
        status.finished = True


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Job Tracker")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    engine = get_engine(settings.database_url)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def get_db():
        with Session(engine) as session:
            yield session

    PAGE_SIZE = 50

    # --- Scrape trigger endpoints ---

    @app.post("/scrape/ats", response_class=HTMLResponse)
    def trigger_scrape_ats(request: Request):
        status = _scrape_jobs["ats"]
        if status.running:
            return HTMLResponse(_scrape_button_html("ats", status))
        with _scrape_lock:
            if status.running:
                return HTMLResponse(_scrape_button_html("ats", status))
            status.running = True
            status.finished = False
            status.error = ""
            status.stats = ""
            status.started_at = datetime.utcnow().strftime("%H:%M:%S")
        cmd = [sys.executable, "-m", "app.cli", "scrape"]
        t = threading.Thread(target=_run_scrape_background, args=("ats", cmd), daemon=True)
        t.start()
        return HTMLResponse(_scrape_button_html("ats", status))

    @app.post("/scrape/byhand", response_class=HTMLResponse)
    def trigger_scrape_byhand(request: Request):
        status = _scrape_jobs["byhand"]
        if status.running:
            return HTMLResponse(_scrape_button_html("byhand", status))
        with _scrape_lock:
            if status.running:
                return HTMLResponse(_scrape_button_html("byhand", status))
            status.running = True
            status.finished = False
            status.error = ""
            status.stats = ""
            status.started_at = datetime.utcnow().strftime("%H:%M:%S")
        cmd = [sys.executable, "-m", "app.cli", "scrape-byhand", "--run-scripts"]
        t = threading.Thread(target=_run_scrape_background, args=("byhand", cmd), daemon=True)
        t.start()
        return HTMLResponse(_scrape_button_html("byhand", status))

    @app.get("/scrape/{key}/status", response_class=HTMLResponse)
    def scrape_status(key: str):
        if key not in _scrape_jobs:
            return HTMLResponse("Unknown", status_code=404)
        return HTMLResponse(_scrape_button_html(key, _scrape_jobs[key]))

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        session: Session = Depends(get_db),
        q: str = "",
        status: Optional[str] = Query(None),
        source: Optional[str] = Query(None),
        location: Optional[str] = Query(None),
        remote: Optional[str] = Query(None),
        job_type: Optional[str] = Query(None),
        category: list[str] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        sort: str = "first_seen",
        order: str = "desc",
        page: int = 1,
    ):
        cat_list = [c for c in (category or []) if c]
        jobs, total = _build_query(
            session, q=q, status=status, source=source, location=location,
            remote=remote, job_type=job_type, categories=cat_list,
            date_from=date_from, date_to=date_to,
            sort=sort, order=order, page=page, page_size=PAGE_SIZE,
        )
        stats = _get_stats(session)
        sources = _get_sources(session)
        all_categories = _get_categories(session)

        return templates.TemplateResponse(request, "index.html", {
            "jobs": jobs,
            "stats": stats,
            "sources": sources,
            "categories": all_categories,
            "selected_categories": cat_list,
            "statuses": [s.value for s in JobStatus],
            "q": q,
            "status": status or "",
            "source": source or "",
            "location": location or "",
            "remote": remote or "",
            "job_type": job_type or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "sort": sort,
            "order": order,
            "page": page,
            "total": total,
            "has_next": page * PAGE_SIZE < total,
        })

    @app.get("/jobs", response_class=HTMLResponse)
    def job_rows(
        request: Request,
        session: Session = Depends(get_db),
        q: str = "",
        status: Optional[str] = Query(None),
        source: Optional[str] = Query(None),
        location: Optional[str] = Query(None),
        remote: Optional[str] = Query(None),
        job_type: Optional[str] = Query(None),
        category: list[str] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        sort: str = "first_seen",
        order: str = "desc",
        page: int = 1,
    ):
        cat_list = [c for c in (category or []) if c]
        jobs, total = _build_query(
            session, q=q, status=status, source=source, location=location,
            remote=remote, job_type=job_type, categories=cat_list,
            date_from=date_from, date_to=date_to,
            sort=sort, order=order, page=page, page_size=PAGE_SIZE,
        )
        return templates.TemplateResponse(request, "_job_rows.html", {
            "jobs": jobs,
            "statuses": [s.value for s in JobStatus],
            "page": page,
            "total": total,
            "has_next": page * PAGE_SIZE < total,
        })

    @app.get("/jobs/{uid}", response_class=HTMLResponse)
    def job_detail(request: Request, uid: str, session: Session = Depends(get_db)):
        job = session.get(Job, uid)
        if not job:
            return HTMLResponse("<p>Job not found</p>", status_code=404)
        events = session.exec(
            select(StatusEvent).where(StatusEvent.job_uid == uid).order_by(col(StatusEvent.at).desc())
        ).all()
        return templates.TemplateResponse(request, "_job_detail.html", {
            "job": job,
            "events": events,
            "statuses": [s.value for s in JobStatus],
        })

    @app.post("/jobs/{uid}/status", response_class=HTMLResponse)
    def update_status(
        request: Request, uid: str, session: Session = Depends(get_db),
        new_status: str = Form(...),
    ):
        job = session.get(Job, uid)
        if not job:
            return HTMLResponse("<p>Job not found</p>", status_code=404)

        old_status = job.status
        job.status = JobStatus(new_status)
        job.status_updated_at = datetime.utcnow()

        event = StatusEvent(
            job_uid=uid,
            from_status=old_status.value if old_status else None,
            to_status=new_status,
            at=datetime.utcnow(),
        )
        session.add(event)
        session.add(job)
        session.commit()
        session.refresh(job)

        return templates.TemplateResponse(request, "_job_row.html", {
            "job": job,
            "statuses": [s.value for s in JobStatus],
        })

    @app.post("/jobs/{uid}/notes", response_class=HTMLResponse)
    def update_notes(
        request: Request, uid: str, session: Session = Depends(get_db),
        notes: str = Form(""),
    ):
        job = session.get(Job, uid)
        if not job:
            return HTMLResponse("<p>Job not found</p>", status_code=404)

        job.notes = notes
        session.add(job)
        session.commit()
        session.refresh(job)

        events = session.exec(
            select(StatusEvent).where(StatusEvent.job_uid == uid).order_by(col(StatusEvent.at).desc())
        ).all()
        return templates.TemplateResponse(request, "_job_detail.html", {
            "job": job,
            "events": events,
            "statuses": [s.value for s in JobStatus],
        })

    @app.get("/export.csv")
    def export_csv(
        session: Session = Depends(get_db),
        q: str = "",
        status: Optional[str] = Query(None),
        source: Optional[str] = Query(None),
        location: Optional[str] = Query(None),
        remote: Optional[str] = Query(None),
        job_type: Optional[str] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        sort: str = "first_seen",
        order: str = "desc",
    ):
        import csv
        import io

        jobs = _build_query(
            session, q=q, status=status, source=source, location=location,
            remote=remote, job_type=job_type, date_from=date_from, date_to=date_to,
            sort=sort, order=order,
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Title", "Company", "Location", "Source", "Published", "Status", "URL", "Remote", "Notes"])
        for j in jobs:
            writer.writerow([j.title, j.company, j.location, j.source, j.published, j.status.value, j.url, j.remote, j.notes])

        from fastapi.responses import StreamingResponse
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=jobs.csv"},
        )

    # --- Companies page ---

    @app.get("/companies", response_class=HTMLResponse)
    def companies_page(request: Request, session: Session = Depends(get_db)):
        companies_with_counts = _get_company_list(session, settings)
        total_jobs = sum(c["job_count"] for c in companies_with_counts)
        return templates.TemplateResponse(request, "companies.html", {
            "companies": companies_with_counts,
            "total_jobs": total_jobs,
        })

    @app.post("/companies", response_class=HTMLResponse)
    def add_company(
        request: Request, session: Session = Depends(get_db),
        provider: str = Form(...), token: str = Form(...), name: str = Form(""),
    ):
        from app.config import ATSCompany
        new_co = ATSCompany(provider=provider, token=token.strip(), name=name.strip() or None)
        # Check for duplicates
        existing = [(c.provider, c.token) for c in settings.ats.companies]
        if (new_co.provider, new_co.token) not in existing:
            settings.ats.companies.append(new_co)
            _save_config(settings)
        companies_with_counts = _get_company_list(session, settings)
        return templates.TemplateResponse(request, "_company_list.html", {
            "companies": companies_with_counts,
        })

    @app.delete("/companies/{provider}/{token}", response_class=HTMLResponse)
    def remove_company(
        request: Request, provider: str, token: str,
        session: Session = Depends(get_db),
    ):
        settings.ats.companies = [
            c for c in settings.ats.companies
            if not (c.provider == provider and c.token == token)
        ]
        _save_config(settings)
        companies_with_counts = _get_company_list(session, settings)
        return templates.TemplateResponse(request, "_company_list.html", {
            "companies": companies_with_counts,
        })

    # --- Career Portals page ---

    @app.get("/portals", response_class=HTMLResponse)
    def portals_page(request: Request, session: Session = Depends(get_db)):
        portal_data = _get_portal_data(session)
        return templates.TemplateResponse(request, "portals.html", portal_data)

    @app.get("/portals/{slug}/jobs", response_class=HTMLResponse)
    def portal_company_jobs(
        request: Request, slug: str, session: Session = Depends(get_db),
    ):
        source = f"portal:{slug}"
        jobs = list(session.exec(
            select(Job)
            .where(Job.source == source)
            .where(Job.status != JobStatus.ARCHIVED)
            .where(Job.status != JobStatus.NOT_RELEVANT)
            .order_by(col(Job.first_seen).desc())
            .limit(100)
        ).all())
        return templates.TemplateResponse(request, "_portal_jobs.html", {
            "jobs": jobs,
            "statuses": [s.value for s in JobStatus],
        })

    # --- By-Hand scrapers page ---

    @app.get("/byhand", response_class=HTMLResponse)
    def byhand_page(request: Request, session: Session = Depends(get_db)):
        data = _get_byhand_data(session)
        return templates.TemplateResponse(request, "byhand.html", data)

    # --- Matches page (semantic ranking sidecar) ---

    @app.get("/matches", response_class=HTMLResponse)
    def matches_page(
        request: Request,
        session: Session = Depends(get_db),
        status: Optional[str] = Query(None),
        min_pct: int = Query(50),
        today_only: bool = Query(False),
    ):
        ctx = _matches_context(
            session, status_filter=status, min_pct=min_pct, today_only=today_only,
        )
        return templates.TemplateResponse(request, "matches.html", {
            **ctx,
            "statuses": [s.value for s in JobStatus],
            "status": status or "",
            "min_pct": min_pct,
            "today_only": today_only,
        })

    @app.get("/matches/jobs", response_class=HTMLResponse)
    def matches_job_rows(
        request: Request,
        session: Session = Depends(get_db),
        status: Optional[str] = Query(None),
        min_pct: int = Query(50),
        today_only: bool = Query(False),
    ):
        ctx = _matches_context(
            session, status_filter=status, min_pct=min_pct, today_only=today_only,
        )
        return templates.TemplateResponse(request, "_matches_rows.html", {
            **ctx,
            "statuses": [s.value for s in JobStatus],
            "status": status or "",
            "min_pct": min_pct,
            "today_only": today_only,
        })

    @app.get("/byhand/{slug}/jobs", response_class=HTMLResponse)
    def byhand_source_jobs(
        request: Request,
        slug: str,
        company: str = Query(default=""),
        session: Session = Depends(get_db),
    ):
        source = f"byhand:{slug}"
        q = (
            select(Job)
            .where(Job.source == source)
            .where(Job.status != JobStatus.ARCHIVED)
            .where(Job.status != JobStatus.NOT_RELEVANT)
        )
        if company:
            q = q.where(Job.company == company)
        jobs = list(session.exec(
            q.order_by(col(Job.first_seen).desc()).limit(200)
        ).all())
        return templates.TemplateResponse(request, "_byhand_jobs.html", {
            "jobs": jobs,
            "statuses": [s.value for s in JobStatus],
            "slug": slug,
        })

    return app


def _build_query(
    session: Session, *, q: str, status: str | None, source: str | None,
    location: str | None, remote: str | None, job_type: str | None,
    categories: list[str] | None = None,
    date_from: str | None, date_to: str | None,
    sort: str, order: str, page: int = 1, page_size: int = 50,
) -> tuple[list[Job], int]:
    stmt = select(Job)

    if not status or "ARCHIVED" not in status:
        stmt = stmt.where(Job.status != JobStatus.ARCHIVED)
    if not status or "NOT_RELEVANT" not in status:
        stmt = stmt.where(Job.status != JobStatus.NOT_RELEVANT)

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            (col(Job.title).ilike(pattern)) | (col(Job.company).ilike(pattern))
        )

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(col(Job.status).in_(statuses))

    if source:
        stmt = stmt.where(Job.source == source)

    if location:
        stmt = stmt.where(col(Job.location).ilike(f"%{location}%"))

    if remote == "yes":
        stmt = stmt.where(Job.remote == True)  # noqa: E712
    elif remote == "no":
        stmt = stmt.where(Job.remote == False)  # noqa: E712

    if job_type:
        stmt = stmt.where(col(Job.job_type).ilike(f"%{job_type}%"))

    if categories:
        # OR: job matches any of the selected categories
        from sqlalchemy import or_
        stmt = stmt.where(or_(*(col(Job.category).ilike(f"%{c}%") for c in categories)))

    if date_from:
        stmt = stmt.where(Job.first_seen >= datetime.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(Job.first_seen <= datetime.fromisoformat(date_to + "T23:59:59"))

    # Count total before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.exec(count_stmt).one()

    sort_col = {
        "first_seen": Job.published,
        "published": Job.published,
        "company": Job.company,
    }.get(sort, Job.published)

    if order == "asc":
        stmt = stmt.order_by(col(sort_col).asc())
    else:
        stmt = stmt.order_by(col(sort_col).desc())

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    return list(session.exec(stmt).all()), total


def _get_stats(session: Session) -> dict:
    total = session.exec(select(func.count()).select_from(Job)).one()
    today = datetime.utcnow().date()
    new_today = session.exec(
        select(func.count()).select_from(Job).where(func.date(Job.first_seen) == str(today))
    ).one()
    status_counts = {}
    for row in session.exec(select(Job.status, func.count()).group_by(Job.status)).all():
        status_counts[row[0]] = row[1]
    return {"total": total, "new_today": new_today, "by_status": status_counts}


def _get_sources(session: Session) -> list[str]:
    rows = session.exec(select(Job.source).distinct()).all()
    return sorted(rows)


def _get_portal_data(session: Session) -> dict:
    """Get portal companies with job counts, new-today counts, and history."""
    import re
    from sqlalchemy import case

    today = datetime.utcnow().date()

    # Get all portal sources with counts
    rows = session.exec(
        select(
            Job.source,
            func.count(),
            func.sum(case((func.date(Job.first_seen) == str(today), 1), else_=0)),
            func.max(Job.first_seen),
        )
        .where(col(Job.source).like("portal:%"))
        .group_by(Job.source)
    ).all()

    companies = []
    total_jobs = 0
    total_new = 0
    for source, count, new_today, last_seen in rows:
        slug = source.replace("portal:", "", 1)
        name = slug.replace("-", " ").title()
        nt = int(new_today or 0)
        companies.append({
            "slug": slug,
            "name": name,
            "job_count": count,
            "new_today": nt,
            "last_scraped": last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else None,
            "source_type": "portal",
        })
        total_jobs += count
        total_new += nt

    # Also include configured companies with 0 jobs
    try:
        from app.scraping.portal_companies import load_companies
        configured = load_companies()
        existing_slugs = {c["slug"] for c in companies}
        for pc in configured:
            s = re.sub(r"[^a-z0-9]+", "-", pc.name.lower()).strip("-")
            if s not in existing_slugs:
                companies.append({
                    "slug": s,
                    "name": pc.name,
                    "job_count": 0,
                    "new_today": 0,
                    "last_scraped": None,
                    "source_type": pc.platform,
                })
    except Exception:
        pass

    companies.sort(key=lambda x: (-x["job_count"], x["name"].lower()))

    # Day-by-day history (last 14 days)
    day_rows = session.exec(
        select(func.date(Job.first_seen), func.count())
        .where(col(Job.source).like("portal:%"))
        .group_by(func.date(Job.first_seen))
        .order_by(func.date(Job.first_seen).desc())
        .limit(14)
    ).all()
    days = [{"date": str(r[0]), "count": r[1]} for r in reversed(day_rows)]
    max_count = max((d["count"] for d in days), default=0)

    return {
        "companies": companies,
        "total_jobs": total_jobs,
        "total_new_today": total_new,
        "days": days,
        "max_count": max_count,
    }


def _get_byhand_data(session: Session) -> dict:
    """Get by-hand scraper sources with job counts, new-today counts, and history."""
    from sqlalchemy import case

    today = datetime.utcnow().date()

    # Aggregate by source AND company so each "row" in the dashboard
    # is a (scraper, company) pair — e.g. mercedes scraper produced
    # Mercedes-Benz + Mercedes-Benz Tech Innovation.
    rows = session.exec(
        select(
            Job.source,
            Job.company,
            func.count(),
            func.sum(case((func.date(Job.first_seen) == str(today), 1), else_=0)),
            func.max(Job.first_seen),
        )
        .where(col(Job.source).like("byhand:%"))
        .group_by(Job.source, Job.company)
    ).all()

    sources_map: dict[str, dict] = {}
    total_jobs = 0
    total_new = 0
    for source, company, count, new_today, last_seen in rows:
        slug = source.replace("byhand:", "", 1)
        nt = int(new_today or 0)
        if slug not in sources_map:
            sources_map[slug] = {
                "slug": slug,
                "name": slug.replace("_", " ").title(),
                "companies": [],
                "job_count": 0,
                "new_today": 0,
                "last_scraped": None,
            }
        s = sources_map[slug]
        s["companies"].append({"company": company, "count": count, "new_today": nt})
        s["job_count"] += count
        s["new_today"] += nt
        if last_seen and (s["last_scraped"] is None or last_seen > s["last_scraped"]):
            s["last_scraped"] = last_seen
        total_jobs += count
        total_new += nt

    # Expand multi-company sources (e.g. workday) into one row per company,
    # keeping a "parent" summary row above them.
    EXPAND_SLUGS = {"workday"}
    sources_raw = list(sources_map.values())
    for s in sources_raw:
        s["last_scraped"] = s["last_scraped"].strftime("%Y-%m-%d %H:%M") if s["last_scraped"] else None
        s["companies"].sort(key=lambda c: -c["count"])

    sources = []
    for s in sorted(sources_raw, key=lambda x: (-x["job_count"], x["name"].lower())):
        if s["slug"] in EXPAND_SLUGS and len(s["companies"]) > 1:
            # Insert a non-clickable header row, then one sub-row per company
            s["is_header"] = True
            s["sub_rows"] = [
                {
                    "slug": s["slug"],
                    "name": c["company"],
                    "company_filter": c["company"],
                    "job_count": c["count"],
                    "new_today": c["new_today"],
                    "last_scraped": s["last_scraped"],
                    "companies": [],
                    "is_sub": True,
                }
                for c in s["companies"]
            ]
            sources.append(s)
        else:
            s["is_header"] = False
            s["sub_rows"] = []
            sources.append(s)

    # Day-by-day history (last 14 days)
    day_rows = session.exec(
        select(func.date(Job.first_seen), func.count())
        .where(col(Job.source).like("byhand:%"))
        .group_by(func.date(Job.first_seen))
        .order_by(func.date(Job.first_seen).desc())
        .limit(14)
    ).all()
    days = [{"date": str(r[0]), "count": r[1]} for r in reversed(day_rows)]
    max_count = max((d["count"] for d in days), default=0)

    return {
        "sources": sources,
        "total_jobs": total_jobs,
        "total_new_today": total_new,
        "days": days,
        "max_count": max_count,
    }


def _get_company_list(session: Session, settings: Settings) -> list[dict]:
    """Return company list with job counts from DB."""
    companies = []
    for c in settings.ats.companies:
        source_prefix = f"ats:{c.provider}:{c.token}"
        count = session.exec(
            select(func.count()).select_from(Job).where(Job.source == source_prefix)
        ).one()
        companies.append({
            "provider": c.provider,
            "token": c.token,
            "name": c.name,
            "job_count": count,
        })
    # Sort: companies with jobs first, then alphabetically
    companies.sort(key=lambda x: (-x["job_count"], (x["name"] or x["token"]).lower()))
    return companies


def _save_config(settings: Settings) -> None:
    """Write current settings back to config.yaml."""
    import yaml
    data = {
        "keywords": settings.keywords,
        "location": settings.location,
        "radius_km": settings.radius_km,
        "published_within_days": settings.published_within_days,
        "database_url": settings.database_url,
        "sources": {
            "arbeitsagentur": settings.sources.arbeitsagentur,
            "arbeitnow": settings.sources.arbeitnow,
            "adzuna": settings.sources.adzuna,
            "ats": settings.sources.ats,
        },
        "adzuna": {
            "app_id": settings.adzuna.app_id,
            "app_key": settings.adzuna.app_key,
        },
        "ats": {
            "companies": [
                {"provider": c.provider, "token": c.token, **({"name": c.name} if c.name else {})}
                for c in settings.ats.companies
            ],
        },
    }
    with open("config.yaml", "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _get_categories(session: Session) -> list[str]:
    rows = session.exec(select(Job.category).where(Job.category != "").distinct()).all()
    # Flatten multi-categories ("AI/ML, NLP" -> ["AI/ML", "NLP"]) and dedupe
    cats: set[str] = set()
    for row in rows:
        for c in row.split(", "):
            if c.strip():
                cats.add(c.strip())
    return sorted(cats)


def _matches_context(
    session: Session,
    *,
    status_filter: str | None,
    min_pct: int,
    today_only: bool = False,
) -> dict:
    """Build template context for the /matches page."""
    from app.embeddings import is_enabled

    if not is_enabled():
        return {
            "enabled": False,
            "has_profile": False,
            "profile_jobs": [],
            "ranked_jobs": [],
            "unembedded_count": 0,
        }

    from app.embeddings.ranker import rank_jobs, unembedded_count, user_profile_vector

    profile = user_profile_vector(session)
    has_profile = profile is not None

    # Profile jobs (APPLIED + SAVED).
    profile_jobs = list(session.exec(
        select(Job)
        .where(col(Job.status).in_([JobStatus.APPLIED, JobStatus.SAVED]))
        .order_by(col(Job.status_updated_at).desc())
    ).all())

    # Determine status filter for ranking.
    statuses = None
    if status_filter:
        statuses = [JobStatus(s.strip()) for s in status_filter.split(",") if s.strip()]

    ranked = rank_jobs(
        session,
        statuses=statuses,
        min_score=min_pct / 100.0,
        limit=200,
        today_only=today_only,
    )

    return {
        "enabled": True,
        "has_profile": has_profile,
        "profile_jobs": profile_jobs,
        "ranked_jobs": ranked,
        "unembedded_count": unembedded_count(session),
    }


def _scrape_button_html(key: str, status: ScrapeStatus) -> str:
    """Return an HTMX-powered button snippet reflecting current scrape status."""
    label = "Refresh ATS" if key == "ats" else "Refresh Big Companies"

    if status.running:
        return (
            f'<div id="scrape-btn-{key}" '
            f'hx-get="/scrape/{key}/status" hx-trigger="every 3s" hx-swap="outerHTML">'
            f'<span class="inline-flex items-center gap-1.5 text-sm text-amber-700 '
            f'bg-amber-50 border border-amber-300 rounded-lg px-3 py-1.5">'
            f'<svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">'
            f'<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" '
            f'stroke-width="4" fill="none"></circle>'
            f'<path class="opacity-75" fill="currentColor" '
            f'd="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path></svg>'
            f'{label}&#8230; (started {status.started_at})</span></div>'
        )

    if status.finished and status.error:
        return (
            f'<div id="scrape-btn-{key}">'
            f'<button hx-post="/scrape/{key}" hx-target="#scrape-btn-{key}" hx-swap="outerHTML" '
            f'class="text-sm text-red-700 bg-red-50 border border-red-300 '
            f'rounded-lg px-3 py-1.5 hover:bg-red-100 cursor-pointer">'
            f'{label} (error — retry?)</button>'
            f'<p class="text-xs text-red-500 mt-1">{status.error[:120]}</p></div>'
        )

    if status.finished:
        return (
            f'<div id="scrape-btn-{key}">'
            f'<button hx-post="/scrape/{key}" hx-target="#scrape-btn-{key}" hx-swap="outerHTML" '
            f'class="text-sm text-green-700 bg-green-50 border border-green-300 '
            f'rounded-lg px-3 py-1.5 hover:bg-green-100 cursor-pointer">'
            f'{label} &#10003;</button>'
            f'<p class="text-xs text-green-600 mt-1">{status.stats}</p></div>'
        )

    return (
        f'<div id="scrape-btn-{key}">'
        f'<button hx-post="/scrape/{key}" hx-target="#scrape-btn-{key}" hx-swap="outerHTML" '
        f'class="text-sm text-white bg-blue-600 border border-blue-700 '
        f'rounded-lg px-3 py-1.5 hover:bg-blue-700 cursor-pointer">'
        f'{label}</button></div>'
    )


def _default_app() -> FastAPI:
    from app.config import load_settings
    from app.db import init_db

    settings = load_settings()
    init_db(settings.database_url)
    return create_app(settings)


app = _default_app()
