# Budapest Internship Tracker

Collects **internships and student jobs in and around Budapest** from 20 company
career sites (MOL, MVM, Richter, Bosch, Siemens Energy, Henkel, Infineon, P&G, …)
and 5 student-job boards (Zyntern, Mind-Diák, MUISZ, MADS, Schönherz) into one
dashboard on your own computer, where you can search them and track your
applications.

It runs only on your machine: no account, no sign-up, nothing is sent anywhere.

---

## 1. Install on a Mac (once, 2–5 minutes)

**Nothing needs to be installed first** — no Python, no git, no admin password.

1. Open **Terminal**: press `⌘ + Space`, type `Terminal`, press Enter.
2. Copy this whole line, paste it into Terminal (`⌘ + V`), press Enter:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/ibishovrauf/job-tracker/hungary/install-mac.sh | bash
   ```

3. Wait until it says **All done!** If macOS asks *"Terminal would like to access
   files in your Desktop folder"*, click **OK** (that's for the icon).

You now have a **Budapest Jobs** icon on your Desktop, and the app lives in the
`BudapestJobs` folder in your home folder.

**Update** to the newest version any time: run the same line again. Your
settings and saved jobs are kept.

<details>
<summary>Windows, or installing by hand with git</summary>

Install [Python 3.11+](https://www.python.org/downloads/) (Windows: tick **"Add
Python to PATH"**) and [git](https://git-scm.com/downloads), then:

```bash
git clone -b hungary https://github.com/ibishovrauf/job-tracker.git budapest-jobs
cd budapest-jobs
```
Run `./setup.sh` (Mac/Linux) or double-click `setup.bat` (Windows). Then use
`.venv/bin/job-tracker serve` (Windows: `.venv\Scripts\job-tracker serve`) and
open http://127.0.0.1:8000.

> The `main` branch is a different (German) setup — always clone with `-b hungary`.
</details>

## 2. Daily use

**Double-click "Budapest Jobs" on your Desktop.** It:
1. opens the dashboard in your browser, and
2. collects today's new jobs (1–2 minutes) — then refresh the page to see them.

Keep the Terminal window that opens; **close it when you're done** (that stops
the dashboard). Double-clicking again while it's open just reopens the browser.

<details>
<summary>Using the terminal instead</summary>

```bash
cd ~/BudapestJobs
.venv/bin/job-tracker scrape      # collect new jobs
.venv/bin/job-tracker serve       # dashboard at http://127.0.0.1:8000 (Ctrl+C stops it)
```
The **Refresh ATS** button in the dashboard also collects new jobs.
</details>

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

Your settings file is `~/BudapestJobs/config.yaml` (in Finder: *Go → Home →
BudapestJobs*). After editing, test just the part you changed in Terminal:

```bash
cd ~/BudapestJobs
.venv/bin/job-tracker check henkel        # a company
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

**Mac:** run `crontab -e` and add:
```
0 8 * * * cd ~/BudapestJobs && .venv/bin/job-tracker scrape >> scrape.log 2>&1
```

**Windows:** open *Task Scheduler* → *Create Basic Task* → Daily, 08:00 →
*Start a program*:
- Program: `C:\Users\<you>\budapest-jobs\.venv\Scripts\job-tracker.exe`
- Arguments: `scrape`
- Start in: `C:\Users\<you>\budapest-jobs`

## 7. Getting updates

Run the install line from step 1 again (if you installed with git: `git pull`).
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
