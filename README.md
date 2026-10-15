# Job Tracker — Hungary edition

A local tool that collects internship and student-job vacancies in and around
**Budapest** and provides a web dashboard to browse, filter, and track
applications. (Branch `hungary`; the original German tracker lives on `main`.)

## Daily use

```bash
job-tracker scrape     # ~1-2 min; fetches all companies + boards
job-tracker serve      # dashboard at http://127.0.0.1:8000
```

## Where jobs come from

**Company career sites** (`ats.companies` in `config.yaml`) — 20 employers incl.
MOL, MVM, Richter, Bosch, Siemens Energy, Henkel, Infineon, P&G, Veolia, Formlabs.
Each platform has a connector:

| Platform | Companies |
|---|---|
| Taleo | MOL |
| karrierportal.hu | MVM (works for any `<x>.karrierportal.hu`) |
| hrfelho.hu | Roust (works for any `<x>.hrfelho.hu`) |
| SAP SuccessFactors | Richter, X-Chem, Tetra Pak, Audi |
| Workday | GE Vernova, Flowserve, Morgan Stanley, BlackRock |
| SmartRecruiters | Bosch, Louis Dreyfus |
| Greenhouse | Formlabs |
| Avature / Cornerstone / Eightfold / Oracle / Phenom | Siemens Energy / Henkel / Infineon / Emerson / P&G |

**Student-job boards** (`hu_boards` in `config.yaml`): Zyntern, Mind-Diák, MUISZ,
MADS, Schönherz. These only list student jobs, so the title-keyword filter is
skipped and each board is narrowed to **English-friendly** ads instead (English
category/search, or the ad itself written in English). Profession.hu is supported
but **off by default** — read their terms of use before enabling it.

## Filters

- **Keywords** (`keywords`): English + Hungarian (`gyakornok` = intern,
  `diákmunka` = student job, `trainee`, `working student`). With
  `match_title_only: true` they must appear in the job **title**.
- **Location** (`location_filter`): kept only if the location names Budapest or a
  nearby town (Budaörs, Törökbálint, Gödöllő, Cegléd, …). Accent-insensitive.
  Add `Hungary` to accept anywhere in the country.
- **Language** (`hu_boards.skip_native_hungarian`): drops board ads that need
  native/fluent Hungarian. Company-site jobs are not language-filtered — titles
  in Hungarian usually mean Hungarian is required.

## Adding a company

Add a line under `ats.companies`. For Workday, copy host and site from the
careers URL: `https://ms.wd5.myworkdayjobs.com/External` →
`{ provider: workday, token: ms, host: ms.wd5.myworkdayjobs.com, site: External }`.
Other platforms' required params are documented at the top of each connector in
`app/scraping/ats_extra.py`.

## Quick Setup (one command)

**Mac / Linux:**
```bash
./setup.sh
```

**Windows:**
```
setup.bat
```

This installs uv (if needed), creates a virtual environment, installs all dependencies, copies the default config, and runs an initial scrape.

## Manual Setup

```bash
# Clone and install
uv venv .venv && source .venv/bin/activate
uv pip install -e .

# Create your config
cp config.example.yaml config.yaml
# Edit config.yaml — adjust keywords, location, and add ATS companies
```

## Usage

### Scrape vacancies

```bash
job-tracker scrape                # fetch from all enabled sources
job-tracker scrape --dry-run      # preview without writing to DB
```

### Open the dashboard

```bash
job-tracker serve                 # http://127.0.0.1:8000
job-tracker serve --port 9000     # custom port
```

### Quick stats

```bash
job-tracker stats
```

## Sources

| Source | Auth | Notes |
|---|---|---|
| Bundesagentur für Arbeit | None (public API key) | Germany's largest vacancy DB |
| Arbeitnow | None | Tech/startup roles, DE-AT-CH |
| Adzuna | Free API key | Aggregator; set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` env vars or in config |
| Company career boards | None | Greenhouse, Lever, Ashby, Personio — configured per company |

## Adding company career boards

Add entries to `ats.companies` in `config.yaml`:

```yaml
ats:
  companies:
    - { provider: greenhouse, token: spotify, name: Spotify }
    - { provider: lever,      token: figma }
    - { provider: ashby,      token: linear, name: Linear }
    - { provider: personio,   token: celonis, name: Celonis }
```

The `token` is the slug from the company's careers URL (e.g. `jobs.lever.co/figma` → token is `figma`). Re-run `job-tracker scrape` to fetch their postings.

## Daily cron example

```bash
# Add to crontab -e
0 8 * * * cd /path/to/job-tracker && .venv/bin/job-tracker scrape >> scrape.log 2>&1
```

## Tests

```bash
uv pip install pytest
pytest
```

All HTTP is mocked — tests pass offline.
