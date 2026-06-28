# Requirements — German Werkstudent / Praktikum / Internship Tracker

> **How to use this document (read first, AI agent):**
> Build the project **phase by phase** in the order given in §11. Keep the app
> runnable at the end of every phase. Write tests that **mock all HTTP** — never
> call the live APIs from tests. Follow the data model in §6 and the tech stack
> in §4 exactly; if you want to deviate or add a dependency, **stop and ask**.
> This project evolves an existing CLI scraper — reuse its two source modules
> rather than reinventing them. Do not implement auto-applying or scrape
> LinkedIn/Indeed/StepStone (see §3 Non-goals).

---

## 1. Summary

A **single-user, local** tool that collects fresh Werkstudent, Praktikum, and
internship vacancies across Germany once a day and lets the user **browse,
search/filter, and track their applications** through a simple local web
dashboard. There is no login, no hosting, no cloud — it runs on the user's own
machine. It has two faces over one shared data layer:

1. **A CLI** that scrapes the sources and writes results to a local database.
2. **A local web dashboard** (served by the same app) to review jobs and move
   each one through an application pipeline: *new → saved → applied → interview
   → offer / rejected*.

Vacancies come from several **legitimate, programmatic sources** (§7): two that
need no key, an aggregator, and a **config-driven list of company career boards**
(ATS feeds) that the user can grow over time without code changes.

## 2. Goals

- Give the user a clean daily shortlist of **genuinely new** postings (never
  re-show a vacancy already seen — including the same role appearing on multiple
  sources).
- Make it fast to **search and filter** the collected jobs.
- Let the user **track each application's status and notes** in one place.
- Make **adding new company boards trivial** — editing config, not code.
- Stay **simple to run locally**: one command to scrape, one to open the
  dashboard, no build step, no required external accounts beyond one free
  optional API key (Adzuna).

## 3. Non-goals (explicitly out of scope)

- Authentication / multi-user / accounts. It is single-user and local only.
- Cloud hosting or deployment configuration.
- **Auto-applying** to jobs (violates employer terms; produces weak
  applications). The tool ends at "here is your shortlist + tracker."
- Scraping LinkedIn / Indeed / StepStone or any site whose terms forbid it. Use
  only the APIs and public feeds in §7.
- AI-generated cover letters, notifications/email — not in this version.
- Mobile or desktop-packaged app.

## 4. Tech stack (use exactly this)

| Concern | Choice | Notes |
| --- | --- | --- |
| Language | **Python 3.11+** | single language for scraper + web |
| CLI | **Typer** | commands: `scrape`, `serve`, `stats` |
| Web framework | **FastAPI** + **Uvicorn** | serves both HTML pages and HTMX fragments |
| ORM + schemas | **SQLModel** (SQLAlchemy + Pydantic) on **SQLite** | models double as validation schemas |
| Templating | **Jinja2** | server-rendered HTML |
| Interactivity | **HTMX** (via CDN) | live filtering + status changes without a JS build |
| Styling | **Tailwind CSS** (via CDN) | no build step |
| HTTP client | **httpx** | for the scrapers |
| XML parsing | **stdlib `xml.etree.ElementTree`** | for the Personio feed — no new dependency |
| Config | **PyYAML** + a Pydantic settings model | `config.yaml`; secrets may come from env |
| Tests | **pytest** + **respx** (or monkeypatch) | mock all network |
| Packaging | **pyproject.toml** (PEP 621) | installable as `job-tracker` |

**No Node, no bundler, no frontend build.** HTMX + Tailwind load from a CDN in the
base template.

## 5. Project structure

```
job-tracker/
├── pyproject.toml
├── config.example.yaml
├── README.md
├── app/
│   ├── __init__.py
│   ├── cli.py                 # Typer entry point (scrape / serve / stats)
│   ├── config.py              # load + validate config.yaml -> Settings
│   ├── db.py                  # engine, get_session(), init_db()
│   ├── models.py              # SQLModel: Job, StatusEvent
│   ├── scraping/
│   │   ├── __init__.py        # REGISTRY {name: SourceClass}
│   │   ├── base.py            # Source ABC + RawJob dataclass
│   │   ├── arbeitsagentur.py  # Bundesagentur fuer Arbeit source
│   │   ├── arbeitnow.py       # Arbeitnow source
│   │   ├── adzuna.py          # Adzuna aggregator source (Phase 6)
│   │   ├── ats.py             # generic ATS reader + provider adapters (Phase 6)
│   │   ├── dedup.py           # uid + cross-source dedup_key helpers
│   │   └── pipeline.py        # fetch -> dedup -> persist; returns new jobs
│   └── web/
│       ├── server.py          # FastAPI app + routes
│       ├── templates/
│       │   ├── base.html
│       │   ├── index.html         # dashboard shell + filter bar + stats
│       │   ├── _job_rows.html     # HTMX fragment: table rows for results
│       │   └── _job_detail.html   # HTMX fragment: detail/notes panel
│       └── static/                # optional extra css/js
└── tests/
    ├── conftest.py            # in-memory DB fixture, sample payloads
    ├── test_parsing.py        # raw API payload -> RawJob mapping (all sources)
    ├── test_pipeline.py       # dedup across runs + across sources
    ├── test_filters.py        # search/filter query logic
    └── test_web.py            # FastAPI TestClient: routes + status changes
```

## 6. Data model

### `Job`
| Field | Type | Notes |
| --- | --- | --- |
| `uid` | str, **PK** | `f"{source}:{external_id}"` |
| `source` | str | `arbeitsagentur` / `arbeitnow` / `adzuna` / `ats:{provider}:{token}` |
| `external_id` | str | refnr, slug, adzuna id, or ATS job id |
| `dedup_key` | str, **indexed** | normalized cross-source key (see §6.1) |
| `title` | str | |
| `company` | str | |
| `location` | str | e.g. `"Stuttgart, Baden-Württemberg"` |
| `url` | str | direct apply/detail link |
| `published` | str | ISO date, best effort, may be `""` |
| `job_type` | str | free text, e.g. `"Praktikum"`, `"remote, part time"` |
| `tags` | str | comma-separated |
| `description` | str \| None | optional, may be filled later |
| `remote` | bool | default `False` |
| `status` | enum `JobStatus` | default `NEW` |
| `notes` | str | default `""` |
| `first_seen` | datetime | set on insert |
| `status_updated_at` | datetime \| None | set when status changes |

`JobStatus` (string enum): `NEW, SAVED, APPLIED, INTERVIEW, OFFER, REJECTED, ARCHIVED`.

### `StatusEvent` (status history / audit trail)
| Field | Type | Notes |
| --- | --- | --- |
| `id` | int, PK autoincrement | |
| `job_uid` | str, FK → Job.uid | |
| `from_status` | str \| None | |
| `to_status` | str | |
| `at` | datetime | |

### 6.1 De-duplication rules
Two levels, both enforced in `dedup.py` + `pipeline.py`:

1. **Exact (per source):** a vacancy is new only if its `uid` is not already in
   `Job`. (`uid = source:external_id`.)
2. **Cross-source (fuzzy):** the same role often appears on several sources
   (Bundesagentur + Adzuna + the company's own ATS). Compute a `dedup_key` and,
   on insert, **skip a job whose `dedup_key` already exists** — the first record
   seen wins and keeps its `status`/`notes`.

`dedup_key = normalize(company) + "|" + normalize(title) + "|" + normalize(location)`
where `normalize()` lowercases, trims, collapses whitespace, strips gender
suffixes like `(m/w/d)`/`(m/f/d)`, and drops common company-form tokens
(`gmbh`, `ag`, `se`, `kg`, `co`, `mbh`).

**Optional refinement (nice-to-have, not required):** assign each source a
priority (direct ATS > Bundesagentur > Adzuna > Arbeitnow); when a duplicate
arrives from a higher-priority source, update only the kept record's `url`/
`source` to the higher-priority one, still preserving `status`/`notes`.

The scrape must **never** overwrite `status` or `notes` of a job already stored.

## 7. External data sources

> **Source contract.** Every source is a class registered in
> `scraping/__init__.py:REGISTRY` under a name, toggled on/off in config, and
> exposing `fetch(settings) -> list[RawJob]`. `RawJob` carries the normalized
> fields from §6 (minus tracking fields). Adding a source = add a class + a
> registry entry + a config toggle. Nothing else changes.
>
> Both keyless APIs are intended for programmatic access. Be polite: pause
> between requests, cap pages, run ~once a day. On any request failure, log it
> and continue with whatever else was fetched — never crash the run. A source
> that is misconfigured (e.g. Adzuna without a key) logs a clear message and is
> skipped.

### 7.1 Bundesagentur für Arbeit ("Jobsuche") — keyless
Germany's largest vacancy database; has a native Praktikum category.

- **Endpoint:** `GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs`
- **Header:** `X-API-Key: jobboerse-jobsuche` (public client id used by the BA app)
- **Query params:** `was` (free-text keyword), `wo` (location; omit for all DE),
  `umkreis` (radius km), `page` (**starts at 1**), `size` (≤100),
  `veroeffentlichtseit` (last N days, 0–100), `angebotsart`
  (`1`=Arbeit, `4`=Ausbildung/Dual, `34`=Praktikum/Trainee),
  `arbeitszeit` (`vz`/`tz`/`snw`/`ho`/`mj`), `pav` (`false` to exclude private placement).
- **Response:** `{"stellenangebote": [...]}`; each item: `titel`, `refnr`,
  `arbeitgeber`, `arbeitsort:{ort,region,plz}`, `aktuelleVeroeffentlichungsdatum`,
  sometimes `externeUrl`.
- **Job link:** `https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}` (use
  `externeUrl` if present).
- **Pagination:** loop `page` from 1; stop on a short page or a 25-page cap; sleep ~0.4s.
- Mapping: `external_id = refnr`.

### 7.2 Arbeitnow — keyless
English-friendly tech/startup/remote roles in DE-AT-CH. Returns everything
paginated; **filter for keywords client-side**.

- **Endpoint:** `GET https://www.arbeitnow.com/api/job-board-api` — no auth
- **Pagination:** `?page=N` (100/page); follow until empty or a ~10-page cap.
- **Response:** `{"data": [...]}`; each item: `slug`, `title`, `company_name`,
  `location`, `url`, `tags[]`, `job_types[]`, `created_at` (unix s),
  `description`, `remote` (bool).
- **Filtering:** keep an item only if any configured keyword appears in
  `title + description + tags + job_types` (case-insensitive); drop items older
  than `published_within_days` via `created_at`; if a location filter is set,
  require it as a substring of `location`.
- Mapping: `external_id = slug`; `remote` from the field; append `"remote"` to
  `job_type` when true.

### 7.3 Adzuna (aggregator) — free API key
A genuine aggregator covering Germany; the biggest single coverage jump. Requires
a free `app_id` + `app_key` from developer.adzuna.com. If keys are absent, the
source is skipped (logged), not fatal.

- **Endpoint:** `GET https://api.adzuna.com/v1/api/jobs/de/search/{page}`
- **Query params:** `app_id`, `app_key`, `what` (keyword), `where` (location,
  optional), `results_per_page` (≤50), `max_days_old` (= `published_within_days`),
  `content-type=application/json`.
- **Response:** `{"results": [...]}`; each item: `id`, `title`,
  `company:{display_name}`, `location:{display_name}`, `redirect_url`, `created`
  (ISO), `description`, `contract_time` (e.g. `part_time`).
- **Pagination:** increment the `{page}` path segment from 1 until fewer than
  `results_per_page` results or a small page cap; respect the free-tier rate
  limit (sleep between calls). Query once per keyword.
- Mapping: `external_id = id`; `url = redirect_url`; `published = created`.

### 7.4 Company career boards (ATS feeds) — keyless, config-driven
Direct-from-employer postings (no ghost jobs). One generic reader handles all
providers; the **list of companies lives in config** (§10) so the user grows it
over time without code changes. For each configured company, fetch its full
board then apply the same client-side keyword filter as Arbeitnow.

Provider endpoints (replace `{token}` with the slug from the company's careers URL):

| Provider | Endpoint | Per-job id | Notes |
| --- | --- | --- | --- |
| `greenhouse` | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `id` | `{"jobs":[{id,title,location:{name},absolute_url,updated_at,content(HTML)}]}` — no server-side search |
| `lever` | `https://api.lever.co/v0/postings/{token}?mode=json` | `id` | array of `{id,text,categories:{team,location,commitment},hostedUrl,createdAt,descriptionPlain}` |
| `ashby` | `https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` | `id` | `{"name":org,"jobs":[{id,title,location,employmentType,jobUrl,publishedDate}]}` |
| `personio` | `https://{token}.jobs.personio.de/xml` | position `id` | XML `<position>` items: `id`, `name`(title), `office`, `recruitingCategory`, `employmentType`; link `https://{token}.jobs.personio.de/job/{id}` |

- Mapping per company: `source = f"ats:{provider}:{token}"`, `external_id = job id`,
  `company =` the optional `name` from config, else the org name in the response,
  else the token. `url =` the provider's hosted/apply URL.
- Each provider adapter is a small function in `ats.py`; a `PROVIDERS` dict maps
  provider name → adapter. Unknown provider in config → clear error.

## 8. Functional requirements (user stories + acceptance criteria)

### FR-1 Scrape on demand (CLI)
*As a user, I run `job-tracker scrape` to fetch the latest vacancies.*
- [ ] Queries every **enabled** source for every configured keyword.
- [ ] Inserts only jobs that are new by both dedup rules (§6.1); prints
      `X new of Y fetched (Z cross-source duplicates skipped)`.
- [ ] Existing jobs' `status`/`notes` are untouched.
- [ ] A failing source/page logs an error and does not abort the run.
- [ ] `--dry-run` fetches and reports but writes nothing.

### FR-2 Browse jobs (dashboard)
*As a user, I open the dashboard and see my collected jobs in a table.*
- [ ] `job-tracker serve` starts the web server and prints the local URL.
- [ ] Default view: all non-archived jobs, newest `first_seen` first.
- [ ] Each row shows title (linked to `url`), company, location, source,
      published, current status, and a notes indicator.
- [ ] A header shows counts per status and "new today".

### FR-3 Search & filter
*As a user, I narrow the list to what's relevant.*
- [ ] Free-text search across title + company.
- [ ] Filters: status (multi), source, location (substring), remote (yes/no),
      `job_type` contains, and date range on `first_seen`.
- [ ] Filtering updates results **without a full page reload** (HTMX swap of the
      `_job_rows` fragment).
- [ ] Filters combine with AND; empty filters are ignored.
- [ ] Sortable by `first_seen`, `published`, `company`.

### FR-4 Application tracking
*As a user, I move each job through my pipeline and keep notes.*
- [ ] Each row has a status control to set
      `NEW/SAVED/APPLIED/INTERVIEW/OFFER/REJECTED/ARCHIVED`.
- [ ] Changing status updates `status` + `status_updated_at` and appends a
      `StatusEvent`; the row reflects it immediately (HTMX swap).
- [ ] A detail panel lets the user view the description and edit free-text
      `notes` (autosaved or save button).
- [ ] Archived jobs are hidden by default but reachable via the status filter.

### FR-5 Stats (CLI)
*As a user, I run `job-tracker stats` for a quick summary.*
- [ ] Prints total jobs, counts per status, and number added today.

### FR-6 Aggregator source (Adzuna)
*As a user, I optionally widen coverage with Adzuna.*
- [ ] When `app_id`/`app_key` are present (config or env), Adzuna is queried per
      keyword with `max_days_old = published_within_days`.
- [ ] When keys are absent, the source logs "skipped: no Adzuna key" and the run
      continues normally.
- [ ] Results are normalized and flow through the same dedup + persist pipeline.

### FR-7 Configurable company boards (ATS)
*As a user, I follow specific employers and can add more anytime.*
- [ ] The ATS source reads `ats.companies` from config: a list of
      `{provider, token, name?}`.
- [ ] For each entry it fetches the provider's public board and keeps only
      keyword-matching roles.
- [ ] **Adding/removing a company requires only a config edit + re-run** — no
      code change, no restart of anything but the next `scrape`.
- [ ] An unreachable board or unknown provider logs an error and is skipped.

### FR-8 Cross-source de-duplication
*As a user, I never see the same role twice.*
- [ ] A role present on multiple sources is stored **once** (first seen wins,
      per §6.1), preserving its `status`/`notes`.
- [ ] The skipped-duplicate count is reported by `scrape`.

## 9. Dashboard UI

- **One page**, server-rendered, styled with Tailwind (CDN), HTMX for
  interactivity. Clean and readable; a personal tool, not a product.
- **Layout:** sticky top bar with search box + filter controls + status-count
  badges; below it the results table (`_job_rows.html` fragment, HTMX target).
- **Status control:** a `<select>` (or button group) per row that POSTs the new
  status and swaps the row.
- **Detail panel:** clicking a row loads `_job_detail.html` into a side panel or
  modal showing description + editable notes.
- **Empty states:** friendly message when no jobs match / DB is empty (tells the
  user to run `job-tracker scrape`).
- Accessibility: real `<label>`s, keyboard-usable controls, sufficient contrast.

## 10. Configuration

A `config.yaml` (with `config.example.yaml` committed), loaded + validated via a
Pydantic settings model in `app/config.py`. **Secrets** (Adzuna keys) may be set
in config OR via environment variables `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`, with
env taking precedence; never commit real keys (`config.yaml` is git-ignored).

```yaml
keywords: [Werkstudent, Werkstudentin, Working Student, Praktikum, Praktikant, Intern, Internship]
location: ""              # "" = all of Germany; else e.g. "Berlin"
radius_km: 50
published_within_days: 2
database_url: "sqlite:///./jobtracker.sqlite3"

sources:
  arbeitsagentur: true
  arbeitnow: true
  adzuna: false           # set true once you add keys below / via env
  ats: true

adzuna:
  app_id: ""              # or env ADZUNA_APP_ID
  app_key: ""             # or env ADZUNA_APP_KEY

# Grow this list anytime — token is the slug in the company's careers URL.
# e.g. jobs.lever.co/spotify -> {provider: lever, token: spotify}
ats:
  companies:
    - { provider: greenhouse, token: examplehq, name: "Example HQ" }
    - { provider: lever,      token: examplehq }
    - { provider: ashby,      token: examplehq }
    - { provider: personio,   token: examplehq }
```

- No secrets are required for the keyless sources (BA uses the public client id).
- Invalid/missing config exits with a clear, actionable message.

## 11. Build plan (do in this order; keep runnable after each phase)

- **Phase 0 — Scaffold.** `pyproject.toml`, package layout, `config.py` + example,
  `db.py` (engine + `init_db`), `models.py` (Job incl. `dedup_key`, StatusEvent,
  JobStatus). `job-tracker --help` works.
- **Phase 1 — Scraping pipeline.** `scraping/base.py`, `arbeitsagentur.py`,
  `arbeitnow.py`, `dedup.py`, `pipeline.py`; wire `scrape` + `stats`. Tests:
  `test_parsing`, `test_pipeline` (mocked HTTP, dedup across two runs). DB fills
  end to end.
- **Phase 2 — Read-only dashboard.** FastAPI app, `base.html` + `index.html` +
  `_job_rows.html`, list view + stats header. `serve` launches it.
- **Phase 3 — Search & filter.** Filter/search query builder + HTMX fragment
  swap. Test: `test_filters`.
- **Phase 4 — Tracking.** Status-change endpoint (+ `StatusEvent`), detail panel
  with notes editing, archive behavior. Test: `test_web` via `TestClient`.
- **Phase 5 — Polish.** README (setup, `scrape`, `serve`, cron example), empty
  states, minor styling, optional CSV export of the current filtered view.
- **Phase 6 — Pluggable sources (coverage).** Add `adzuna.py` (FR-6), `ats.py`
  with the four provider adapters + config-driven company list (FR-7), and
  enforce cross-source dedup in `dedup.py`/`pipeline.py` (FR-8). Tests: Adzuna
  parsing; each ATS provider's parsing (mock JSON + Personio XML); cross-source
  dedup (same role from two sources inserts once and preserves status/notes).

## 12. Non-functional requirements

- **Reliability:** any single source/page failure is logged and skipped, never
  fatal. The dashboard works even if a scrape partially failed.
- **Politeness/rate limits:** sleep between requests; cap pages per source;
  realistic `User-Agent`; respect Adzuna's free-tier limits. Designed for ~1
  run/day.
- **Performance:** filtering thousands of rows feels instant (index `first_seen`,
  `status`, `source`, `dedup_key`).
- **Extensibility:** a new source is one class + one registry entry + one config
  toggle (§7 contract); a new ATS company is one config line.
- **Portability:** runs on macOS/Linux/Windows with only `pip install`. SQLite
  file lives in the project dir.
- **No telemetry, no external calls** beyond the configured job sources.

## 13. Testing

- `pytest` green is the definition of done for each phase.
- **All HTTP is mocked** (respx or monkeypatched httpx); tests pass offline.
- Cover: payload→model mapping for **every** source (BA, Arbeitnow, Adzuna,
  Greenhouse, Lever, Ashby, Personio XML); per-source dedup (run twice → 0 added);
  **cross-source dedup** (same role via two sources → 1 row, status/notes kept);
  keyword/location/recency filtering; filter query logic; status change persists
  + emits a `StatusEvent`; dashboard routes return 200 and render rows;
  Adzuna-without-key is skipped gracefully.

## 14. Definition of done

- `pip install -e .` then `job-tracker scrape` populates the DB from all enabled
  sources; `job-tracker serve` opens a working dashboard where the user can
  search, filter, change status, and edit notes; re-running `scrape` adds only
  new jobs (across runs and across sources) and preserves status/notes; adding a
  company to `ats.companies` and re-running surfaces its keyword-matching roles;
  `pytest` passes offline; README explains setup, the sources, how to add ATS
  companies, and a daily cron example.

## 15. Future (not now)

Email/Telegram daily digest; AI-drafted cover letters; a kanban board view
grouped by status; an "add company" affordance in the dashboard UI (the data is
already structured for it); per-job reminders/follow-up dates; source-priority
canonical-URL selection (§6.1 refinement). Note a residual gap: roles posted
**exclusively** on LinkedIn/Indeed/StepStone are intentionally not collected, as
clean programmatic access isn't available within their terms.
