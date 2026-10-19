# Troubleshooting

Commands below are run in **Terminal** from the app folder: first type
`cd ~/BudapestJobs` (Mac installer) or `cd budapest-jobs` (git install).
On Windows, replace `.venv/bin/job-tracker` with `.venv\Scripts\job-tracker`.

**Most problems on a Mac are fixed by running the install line again** — it
repairs the app and keeps your settings and saved jobs:

```bash
curl -fsSL https://raw.githubusercontent.com/ibishovrauf/job-tracker/hungary/install-mac.sh | bash
```

### The installer says "Something went wrong"

Read the line after it — "no internet connection" and "could not download" are
usually temporary; run the install line again. Otherwise send a screenshot of the
Terminal window to Rauf.

### Double-clicking "Budapest Jobs" does nothing / opens a text editor

Run the install line again; it re-creates the icon. If macOS says the file
"can't be opened", right-click the icon → **Open** → **Open**.

### `command not found` / `'job-tracker' is not recognized`

You're not in the app folder (`cd ~/BudapestJobs`), or the install didn't finish
— run the install line again (Windows/git: `setup.bat` / `./setup.sh`).

### `python3 not found` / `Python 3.11+ required` (Windows / git install only)

The Mac installer brings its own Python, so this only affects the manual setup.
Install Python from [python.org/downloads](https://www.python.org/downloads/).
On Windows, re-run the installer, choose *Modify*, and tick **Add Python to
environment variables**. Close and reopen the terminal afterwards.

### `Error loading config from config.yaml: … line 12, column 5`

There's a typo in `config.yaml` at that line. Usual causes: a tab instead of
spaces, a missing `}` or `]`, or a name with `:`/`|`/`&` that needs quotes.
Compare with the same section in `config.example.yaml`.

### The dashboard page won't open

- Is the Terminal window from "Budapest Jobs" still open? Closing it stops the
  dashboard — double-click the icon again.
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

Install on the new computer, then copy two files from the old `BudapestJobs`
folder into the new one (replace the existing ones):
`config.yaml` (your settings) and `jobtracker.sqlite3` (your jobs, statuses and notes).
