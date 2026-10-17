# Configuration reference

All settings live in `config.yaml` in the project folder. It was created from
`config.example.yaml` during setup. Edit it with any text editor (TextEdit on
Mac: *Format → Make Plain Text*; Notepad on Windows).

YAML tips:
- Indentation matters — use **spaces, never tabs**, and keep items lined up.
- `#` starts a comment; the rest of the line is ignored.
- Text with special characters (`:`, `#`, `&`, `|`) needs quotes: `name: "Emerson | NI"`.

If the file has a mistake, every command prints `Error loading config from
config.yaml: …` with the line number.

---

## Keywords

```yaml
keywords:
  - Intern
  - Internship
  - Gyakornok
  ...
match_title_only: true
```

A company job is kept only if its **title** contains one of these words
(whole words, not case-sensitive — `Intern` matches "HR Intern" but not
"Internal Audit").

- Add words for other kinds of roles, e.g. `Junior`, `Graduate`,
  `Pályakezdő` (career starter), `Szakmai gyakorlat` (work placement).
- `match_title_only: false` also searches the job description. You'll get more
  results, but also senior jobs that just mention "working with interns".

Keywords are **not** applied to the student job boards (everything there is
already a student job).

## Locations

```yaml
location_filter:
  - Budapest
  - Budaörs
  - Gödöllő
  ...
```

A job is kept only if its location mentions one of these names. Accents and
capitals don't matter (`Budaors` = `Budaörs`).

- **Add a town:** add a line, e.g. `- Győr` (to see AUDI HUNGARIA jobs) or
  `- Székesfehérvár`.
- **All of Hungary:** add `- Hungary` and `- Magyarország`.
- **No location filter at all:** `location_filter: []` (not recommended: big
  companies would show jobs from every country).

Run `job-tracker check <company>` to see which jobs a change lets through — the
`-` lines show what is being filtered out and why.

## Student job boards

```yaml
sources:
  hu_boards: true          # false turns off all boards at once

hu_boards:
  zyntern: true
  minddiak: true
  muisz: true
  mads: true
  schonherz: true
  profession: false
  skip_native_hungarian: true
```

| Board | What is collected |
|---|---|
| `zyntern` | Internships + student jobs in Budapest that list English |
| `minddiak` | Mind-Diák ads that are **written in English** |
| `muisz` | MUISZ's English site (already hides Hungarian-only jobs) |
| `mads` | MADS "SSC/BSC" category (international service centres) + search for "english" |
| `schonherz` | Schönherz "jobs for foreign students" + search for "english" (first page of each) |
| `profession` | Profession.hu internships and student jobs in Budapest with English. **Off by default** — it's the biggest source, but check their terms of use first: https://www.profession.hu |

**`skip_native_hungarian: true`** drops ads that require native-level Hungarian
(Zyntern) or that are written in Hungarian (Mind-Diák). Set it to `false` once
your Hungarian is good enough to want those too — you'll get many more results.

Mind-Diák, MUISZ and Schönherz often don't name the employer; those rows show
"client undisclosed". The company appears once you open the ad.

## Company career sites

```yaml
sources:
  ats: true

ats:
  companies:
    - { provider: workday, token: ms, host: ms.wd5.myworkdayjobs.com, site: External, name: Morgan Stanley }
```

See [ADDING_A_COMPANY.md](ADDING_A_COMPANY.md). Each line is one company:

| Field | Meaning |
|---|---|
| `provider` | Which hiring platform the company uses |
| `token` | The company's ID on that platform |
| `name` | What the dashboard shows (any text you like) |
| `host`, `site` | Web address parts — only for some platforms (Workday, SuccessFactors, …) |
| `params` | Extra platform-specific settings — copy from an existing entry |

## Other settings

| Setting | Default | Meaning |
|---|---|---|
| `database_url` | `sqlite:///./jobtracker.sqlite3` | Where your jobs, statuses and notes are stored. Back up this file to keep your history. |
| `published_within_days` | `14` | Not used by the Hungarian sources (they return everything currently open). |
| `sources.arbeitsagentur` / `arbeitnow` / `adzuna` / `byhand` / `portals` | `false` | German sources from the original project. Leave them off. |

## Starting over

- **Reset settings:** delete `config.yaml` and copy `config.example.yaml` to
  `config.yaml` again.
- **Delete all collected jobs** (including your statuses and notes!): delete
  `jobtracker.sqlite3`, then run `scrape`.
