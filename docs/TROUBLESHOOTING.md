# Troubleshooting

On Windows, replace `.venv/bin/job-tracker` with `.venv\Scripts\job-tracker`
everywhere below.

### `command not found` / `'job-tracker' is not recognized`

You're not in the project folder, or setup didn't finish. Run `cd budapest-jobs`
(or wherever you cloned it), then use the full path `.venv/bin/job-tracker …`.
If `.venv` doesn't exist, run `./setup.sh` / `setup.bat` again.

### `python3 not found` / `Python 3.11+ required`

Install Python from [python.org/downloads](https://www.python.org/downloads/).
On Windows, re-run the installer, choose *Modify*, and tick **Add Python to
environment variables**. Close and reopen the terminal afterwards.

### `Error loading config from config.yaml: … line 12, column 5`

There's a typo in `config.yaml` at that line. Usual causes: a tab instead of
spaces, a missing `}` or `]`, or a name with `:`/`|`/`&` that needs quotes.
Compare with the same section in `config.example.yaml`.

### The dashboard page won't open

- Is `job-tracker serve` still running in a terminal? Closing that terminal stops it.
- Use **http://127.0.0.1:8000** (not https).
- `address already in use` → it's already running in another terminal, or use
  another port: `job-tracker serve --port 8001` and open http://127.0.0.1:8001.

### A scrape says `0 new of 0 fetched`

- Check your internet connection.
- Check that `sources: ats: true` and `hu_boards: true` in `config.yaml`.
- Run `job-tracker check mol` — if that fails too, it's the connection.

### A scrape finds fewer jobs than yesterday

Normal: positions close and the tool only adds **new** ones. Jobs you already
have stay in the dashboard. `0 new` simply means nothing new was posted.

### One company / board stopped working

Websites change. Run `job-tracker check <name>`:
- `FAILED: 404` or `0 postings fetched` for a company that used to work → it
  probably moved to another platform. Look it up again with
  [ADDING_A_COMPANY.md](ADDING_A_COMPANY.md).
- A board fails → turn it off in `config.yaml` (`hu_boards: <board>: false`)
  and tell Rauf; the rest keeps working.

A broken source never stops the others — the scrape logs a warning and continues.

### I see a job outside Budapest

Some employers label jobs inconsistently (e.g. a few Richter postings titled
"… - Debrecen" are tagged "Budapest"). Mark it `NOT_RELEVANT` — it disappears
from the list.

### I want to see the jobs I marked NOT_RELEVANT again

Use the **Status** filter and pick `NOT_RELEVANT` (or `ARCHIVED`).

### I see a job in Hungarian I can't do

Company jobs aren't language-filtered. Mark it `NOT_RELEVANT`. To get mostly
English results, search the dashboard for English words like `Intern` or
`Trainee` instead of `gyakornok`.

### Moving to a new computer

Copy two files from the old project folder into the new one after setup:
`config.yaml` (your settings) and `jobtracker.sqlite3` (your jobs, statuses and notes).
