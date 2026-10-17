# Budapest Internship Tracker

Collects **internships and student jobs in and around Budapest** from 20 company
career sites (MOL, MVM, Richter, Bosch, Siemens Energy, Henkel, Infineon, P&G, …)
and 5 student-job boards (Zyntern, Mind-Diák, MUISZ, MADS, Schönherz) into one
dashboard on your own computer, where you can search them and track your
applications.

It runs only on your machine: no account, no sign-up, nothing is sent anywhere.

> This is the `hungary` branch. The `main` branch is a different (German) setup —
> make sure you cloned with `-b hungary`.

---

## 1. Install (once, ~5 minutes)

You need **Python 3.11 or newer** and **git**.

| | Mac | Windows |
|---|---|---|
| Python | [python.org/downloads](https://www.python.org/downloads/) | [python.org/downloads](https://www.python.org/downloads/) — tick **"Add Python to PATH"** in the installer |
| git | run `git --version` in Terminal; macOS offers to install it | [git-scm.com/download/win](https://git-scm.com/download/win) |

Then open **Terminal** (Mac) or **Command Prompt** (Windows) and run:

```bash
git clone -b hungary https://github.com/ibishovrauf/job-tracker.git budapest-jobs
cd budapest-jobs
```

Then the setup script — it installs everything, creates your `config.yaml`, and
does a first collection of jobs:

- **Mac:** `./setup.sh`
- **Windows:** double-click `setup.bat` (or run `setup.bat`)

## 2. Daily use

Open a terminal in the `budapest-jobs` folder:

| What | Mac | Windows |
|---|---|---|
| Collect new jobs (~1–2 min) | `.venv/bin/job-tracker scrape` | `.venv\Scripts\job-tracker scrape` |
| Open the dashboard | `.venv/bin/job-tracker serve` | `.venv\Scripts\job-tracker serve` |

With the dashboard running, open **http://127.0.0.1:8000** in your browser.
Stop it with `Ctrl+C` in the terminal.

You can also collect jobs from inside the dashboard: the **Refresh ATS** button
(top right) runs the same collection in the background.

> If you installed [uv](https://docs.astral.sh/uv/) you can instead type
> `uv run job-tracker scrape` / `uv run job-tracker serve` on both systems.

## 3. Using the dashboard

- **Status** (dropdown on each row): move a job through
  `NEW → SAVED → APPLIED → INTERVIEW → OFFER / REJECTED`, or mark it
  `NOT_RELEVANT` to hide it. Jobs already seen are never shown as new again.
- **Click a title** to see details and write **notes** (contact person, deadline…).
- **Search / filters**: title or company, category, location
  (e.g. `Budapest XIII`), source, date range.
- **Export CSV** downloads everything, including your statuses and notes.
- Ignore the *Big Companies*, *Portals* and *Matches* pages — they belong to the
  German setup.

## 4. Changing what it looks for

Everything is in **`config.yaml`** (open it with any text editor).

- **Add a company** → [docs/ADDING_A_COMPANY.md](docs/ADDING_A_COMPANY.md)
- **Keywords, towns, job boards, Hungarian-language filter** →
  [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- **Something not working?** → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

After editing, test just the part you changed:

```bash
.venv/bin/job-tracker check henkel        # a company (Windows: .venv\Scripts\job-tracker check henkel)
.venv/bin/job-tracker check zyntern       # a job board
```

It prints every job it found and why anything was dropped — it doesn't change
your saved jobs.

## 5. What it filters by default

| Filter | Default | Change it in |
|---|---|---|
| Job title must contain | Intern, Internship, Trainee, Working Student, Student, Gyakornok, Diákmunka, Diák … | `keywords` |
| Location must be | Budapest or a nearby town (Budaörs, Gödöllő, Érd, Cegléd, …) | `location_filter` |
| Language | job-board ads that require native Hungarian are dropped | `hu_boards.skip_native_hungarian` |

Company career-site jobs are **not** language-filtered. A Hungarian title
(e.g. *Pénzügyi gyakornok*) usually means Hungarian is required; English titles
are usually fine for English speakers.

## 6. Run it automatically every morning (optional)

**Mac:** run `crontab -e` and add (adjust the path):
```
0 8 * * * cd ~/budapest-jobs && .venv/bin/job-tracker scrape >> scrape.log 2>&1
```

**Windows:** open *Task Scheduler* → *Create Basic Task* → Daily, 08:00 →
*Start a program*:
- Program: `C:\Users\<you>\budapest-jobs\.venv\Scripts\job-tracker.exe`
- Arguments: `scrape`
- Start in: `C:\Users\<you>\budapest-jobs`

## 7. Getting updates

```bash
git pull
```
Your `config.yaml` and saved jobs are never touched by updates. New companies
added to `config.example.yaml` upstream can be copied into your `config.yaml`
by hand.

---

### For developers

```bash
uv sync && uv run --with pytest pytest     # all HTTP is mocked; runs offline
```
Connectors: `app/scraping/ats.py` (Greenhouse, Lever, Ashby, SmartRecruiters,
Personio, Workday), `app/scraping/ats_extra.py` (Taleo, SuccessFactors, Oracle,
Eightfold, Phenom, Avature, Cornerstone, karrierportal.hu, hrfelho.hu, Veolia),
`app/scraping/hu_boards.py` (student boards). Every site was checked against its
robots.txt; please keep request rates low.
