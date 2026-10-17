# Adding a company

Companies don't build their own job pages — almost all of them rent a hiring
platform (an "ATS"). This tool can read 16 of those platforms. To add a company
you only need to find out **which platform** it uses and **one or two names**
from its job-page web address.

## Step 1 — Find the company's job listing

Go to the company's careers page and click through to the actual **list of open
positions**, then click on **one job**. Look at the web address (URL) in your
browser — that is where the clues are.

## Step 2 — Match the address to a platform

Find the row whose pattern matches. Words in `CAPITALS` are what you copy.

### Easy ones (one name to copy)

| If the job URL looks like… | Add this line to `config.yaml` |
|---|---|
| `boards.greenhouse.io/TOKEN/…` or `job-boards.greenhouse.io/TOKEN/…` | `- { provider: greenhouse, token: TOKEN, name: Company }` |
| `jobs.lever.co/TOKEN/…` | `- { provider: lever, token: TOKEN, name: Company }` |
| `jobs.ashbyhq.com/TOKEN/…` | `- { provider: ashby, token: TOKEN, name: Company }` |
| `jobs.smartrecruiters.com/TOKEN/…` or `careers.smartrecruiters.com/TOKEN` | `- { provider: smartrecruiters, token: TOKEN, name: Company, params: { country: hu } }` |
| `TOKEN.jobs.personio.de/…` or `TOKEN.jobs.personio.com/…` | `- { provider: personio, token: TOKEN, name: Company }` |
| `TOKEN.karrierportal.hu/…` | `- { provider: karrierportal, token: TOKEN, name: Company }` |
| `TOKEN.hrfelho.hu/…` | `- { provider: hrfelho, token: TOKEN, name: Company }` |
| `TOKEN.csod.com/ux/ats/careersite/…` (Cornerstone) | `- { provider: csod, token: TOKEN, name: Company, params: { country: hu } }` |

### Workday (very common for big international companies)

URL looks like `https://TENANT.wd3.myworkdayjobs.com/SITE/job/…`
(the `wd3` number varies: wd1, wd3, wd5, wd103 …).

Example: `https://ms.wd5.myworkdayjobs.com/External/job/Budapest-Hungary/…`

```yaml
- { provider: workday, token: ms, host: ms.wd5.myworkdayjobs.com, site: External, name: Morgan Stanley }
```
- `token` = the first part of the host (before `.wd5`)
- `host` = everything between `https://` and the next `/`
- `site` = the first part of the path (may be `en-US/External` — then use only `External`)

### SAP SuccessFactors

Career sites whose job links look like `https://HOST/job/Budapest-Some-Title/1234567/`
and whose search page is `https://HOST/search/?q=…`.

Check it: open `https://HOST/googlebase.xml` in your browser. If you see a long
list of jobs (XML text), it works:

```yaml
- { provider: successfactors, token: shortname, host: HOST, name: Company, params: { country: HU } }
```

### Harder ones (need an ID from the website's internals)

These platforms are supported, but finding the IDs requires the browser's
developer tools. Copy an existing entry from `config.example.yaml` as a model:

| URL contains | Platform | Example entry in config.example.yaml |
|---|---|---|
| `.taleo.net/careersection/` | Oracle Taleo | MOL |
| `.oraclecloud.com/hcmUI/CandidateExperience/` | Oracle Recruiting | Emerson |
| `/api/pcsx/` or "Powered by Eightfold" | Eightfold | Infineon |
| `/widgets` or "phenom" in page source | Phenom | Procter & Gamble |
| `/FolderDetail/` | Avature | Siemens Energy |

If you get stuck on one of these, ask Rauf — or skip it and set up an email job
alert on the company's site instead.

## Step 3 — Test it

Save `config.yaml`, then:

```bash
.venv/bin/job-tracker check "Company"           # Windows: .venv\Scripts\job-tracker check "Company"
```

(Use any part of the `name` or `token` you wrote.) You'll see one of:

| Output | Meaning |
|---|---|
| `120 postings fetched, 3 match keywords, 2 kept…` and a list | ✅ Working. The `+` lines are what you'll see in the dashboard. |
| `120 postings fetched, 0 match keywords` | ✅ Working — the company just has no internships right now. It will be checked every day. |
| `0 postings fetched` | ⚠️ Probably a wrong token/host, or the site truly has no openings. Re-check the URL. |
| `FAILED: … 404 Not Found` | ❌ Wrong token / host / site. Re-check spelling (it's case-sensitive for SmartRecruiters and Workday). |
| `FAILED: unknown provider` | ❌ Typo in `provider:`. The message lists the valid names. |
| `- Some Intern | Debrecen (location filtered out)` | The job exists but isn't in a town on your list. See [CONFIGURATION.md](CONFIGURATION.md#locations). |

Once `check` shows what you expect, the next `scrape` (or **Refresh ATS** in the
dashboard) will add those jobs.

## The company doesn't use any of these platforms

Some companies (e.g. Pannonia Bio, Müssig) post jobs only on their own website
or not at all. Those can't be added without new code. Alternatives: check
whether the same jobs appear on **Zyntern**, **Profession.hu**, or LinkedIn, or
sign up for the company's own job-alert email.

## Removing a company

Delete its line from `config.yaml` (or put `#` at the start of the line).
Jobs already collected stay in the dashboard.
