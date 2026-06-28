# Job Tracker

A local tool that collects Werkstudent, Praktikum, and internship vacancies
across Germany and provides a web dashboard to browse, filter, and track
applications.

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
