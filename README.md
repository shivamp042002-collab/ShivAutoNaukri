# JobSailor

Auto-apply bot for **Naukri.com**. It searches for **recent** software / backend developer jobs that ask for
**0–3 years** of experience, applies to them, answers the extra questions Naukri asks using the **Gemini API**, and
keeps a CSV of everything it did so the next run never repeats a job.

> ⚠️ Automating applications may violate Naukri's Terms of Service and can get an account flagged or suspended.
> Use it at your own risk, with sensible limits, and read what it applies to.

## Features

| | |
|---|---|
| **50 applications per run** | Keeps going until 50 jobs are *successfully* applied (configurable). Expired / external-site / already-applied jobs don't count toward the 50. |
| **Never applies twice** | Every job it touches is appended to `data/applied_jobs.csv` immediately. The next run skips anything already applied, expired, or sent to a company site. Failed jobs are retried up to 2 times, then dropped. |
| **Experience 0–3 years only** | Accepts `0-1`, `0-2`, `0-3`, `1-2`, `1-3`. Rejects anything whose minimum is above 1 or maximum above 3 (e.g. `2-4`, `3-5`, `0-5`). Both limits are configurable. |
| **Freshest jobs first** | Searches the **last 24 hours** first, then widens to the **last 7 days** only if it needs more jobs. Applies newest → oldest. Anything older than 7 days is never applied to. |
| **Gemini answers questions** | Radio buttons, multi-select, chips and free-text questions are answered from your `profile.json`. Uses the current `google-genai` SDK with model fallbacks. |
| **Your own fixed answers** | `"answers"` in `profile.json` (notice period, CTC, relocation…) are used first, with no API call. |
| **Answer cache + audit log** | The same question never costs a second API call. `data/questions_answers.csv` records every question and the answer given, so you can review it. |
| **Dry-run mode** | `--dry-run` finds and filters jobs but applies to none. |
| **Smart title filter** | Developer / engineer roles only; skips senior, lead, manager, QA, intern, sales, etc. |
| **Company blacklist, skill-match score** | Optional. |
| **Crash-safe** | Progress is saved after every single job. Ctrl+C is safe. |
| **Excel-lock safe** | If `applied_jobs.csv` is open in Excel, rows go to `applied_jobs_pending.csv` instead of being lost. |
| **Log file + stats** | `data/jobsailor.log`, and `python main.py --stats` shows your history. |

## Quick start

### 1. Requirements
- Python 3.9+
- Mozilla **Firefox** installed
- A Gemini API key (free): <https://aistudio.google.com/apikey>

No need to download geckodriver – Selenium downloads the right one automatically.

### 2. Install

```bash
git clone https://github.com/<your-username>/JobSailor.git
cd JobSailor

python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure

```bash
# Windows:  copy .env.example .env      &  copy profile.example.json profile.json
# Mac/Linux: cp .env.example .env       &  cp profile.example.json profile.json
```

1. Open **`.env`** and paste your key: `GEMINI_API_KEY=AIza...`
2. Open **`profile.json`** and fill in your real details (experience, CTC, notice period, skills, …).
   Gemini answers *only* from this file, so the more accurate it is, the better the answers.
   Put anything that must always be answered the same way under `"answers"`.
3. (Optional) edit **`config.py`** – keywords, number of jobs, experience limits, blacklist.

### 4. First run – try a dry run

```bash
python main.py --dry-run
```

Firefox opens. **Log in to Naukri once** when prompted, then press Enter in the terminal. The login is remembered in
`data/firefox_profile`. The dry run writes the jobs it *would* apply to into `data/dry_run_candidates.csv`.

### 5. Real run

```bash
python main.py
```

Windows shortcut: double-click **`run.bat`**. macOS/Linux: `./run.sh`.

At the end you get a summary and the full record in `data/applied_jobs.csv`.

### Command-line options

```
python main.py                      apply to up to 50 jobs
python main.py --max 20             apply to up to 20 jobs
python main.py --dry-run            search + filter only
python main.py --keywords "Python Developer,Java Developer"
python main.py --headless           no browser window (Naukri may block this more often)
python main.py --stats              summary of everything done so far
```

## Output files (`data/`)

| File | Contents |
|---|---|
| `applied_jobs.csv` | `timestamp, status, job_id, title, company, location, experience, posted_age_days, match_score, questions_answered, detail, url` — status is `applied`, `already_applied`, `external_site`, `expired`, `low_match` or `failed` |
| `questions_answers.csv` | Every question Naukri asked + the answer and where it came from (`gemini` / `cache` / `profile`) |
| `answer_cache.json` | Cached Gemini answers (delete a line to force a re-ask) |
| `jobsailor.log` | Detailed log |
| `dry_run_candidates.csv` | Output of `--dry-run` |

These files are in `.gitignore` – your personal data, API key and login never get uploaded to GitHub.

## How it decides

1. **Search** – for each keyword × experience value × page it opens
   `naukri.com/<keyword>-jobs?...&jobAge=1` (last 24 h) and, only if more jobs are needed, `jobAge=7`.
2. **Filter** – title, company blacklist, experience range, age. Job age comes from the "posted X days ago" text on the
   card; if that's missing it falls back to the posting date encoded in the job ID (the first 6 digits of a Naukri job ID
   are `DDMMYY`).
3. **Skip history** – anything in `applied_jobs.csv` is dropped.
4. **Sort** – last-24 h jobs first, then by age ascending.
5. **Apply** – open job → skip if already applied / expired / company-site → click **Apply** → answer chatbot questions
   with Gemini → confirm the "successfully applied" message → write the CSV row → pause 2–5 s → next job.

## Settings cheat-sheet (`config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `MAX_APPLY_PER_RUN` | 50 | successful applications per run |
| `MAX_ALLOWED_MIN_EXPERIENCE` | 1 | highest *minimum* experience accepted (1 ⇒ `0-x` and `1-x`) |
| `MAX_ALLOWED_MAX_EXPERIENCE` | 3 | highest *maximum* experience accepted |
| `RECENCY_TIERS_DAYS` | `[1, 7]` | search last 24 h first, then 7 days |
| `MAX_JOB_AGE_DAYS` | 7 | hard cap on job age |
| `SEARCH_KEYWORDS` | 10 dev roles | add / remove roles |
| `SEARCH_EXPERIENCE_VALUES` | `[1, 2]` | experience values used in Naukri's own filter |
| `BLACKLIST_COMPANIES` | `[]` | company names to skip |
| `MIN_MATCH_SCORE` | 0 (off) | skip jobs matching fewer % of your `profile.json` skills |
| `MAX_RETRY_FAILED` | 2 | retries for a job that failed |
| `GEMINI_MODEL` | `gemini-flash-latest` | override in `.env` if needed |

Any of them can also be set in `.env`, e.g. `MAX_APPLY_PER_RUN=30`.

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -t .      # or:  pytest
```

The tests cover the experience / recency / title rules, the CSV memory (second run never repeats), the Gemini answer
parsing and fallbacks, search-result parsing, and the apply flow against a simulated Naukri chatbot. They do **not**
hit the real Naukri site.

## Troubleshooting

| Problem | Fix |
|---|---|
| `GEMINI_API_KEY is missing` | Create `.env` from `.env.example` and paste your key. |
| `profile.json not found` | `copy profile.example.json profile.json` and edit it. |
| Fewer than 50 applied | Not enough *fresh, matching, not-yet-applied* jobs. Add keywords in `config.py`, or run again later. |
| `failed – could not answer: …` | Add that question's keyword to `"answers"` in `profile.json` (see `data/questions_answers.csv`). |
| `failed – no recognisable question` / Apply button not found | Naukri changed its HTML. Update the selector lists at the top of `jobsailor/applier.py` (`APPLY_BUTTON_XPATHS`, `SAVE_BUTTON_XPATHS`, `RADIO_CSS`, …). |
| Captcha / "access denied" | Solve it in the browser window, then press Enter in the terminal. Lower `MAX_APPLY_PER_RUN` and don't run it many times a day. |
| Firefox not found | Set `FIREFOX_BINARY=C:\Program Files\Mozilla Firefox\firefox.exe` in `.env`. |
| `applied_jobs.csv` locked | Close it in Excel; meanwhile rows are saved to `applied_jobs_pending.csv`. |
| Login asked every run | Don't delete `data/firefox_profile`. |

## Project layout

```
main.py                  entry point / CLI
config.py                all settings
profile.example.json     template for your personal details (copy to profile.json)
.env.example             template for your API key (copy to .env)
jobsailor/
  browser.py             Firefox start-up, login, captcha detection
  search.py              Naukri search URLs, result parsing, 24h -> 7d candidate collection
  filters.py             title / experience / recency rules and ordering
  tracker.py             CSV memory (no repeat applications)
  applier.py             open job, click Apply, answer chatbot questions
  gemini_client.py       Gemini answers, profile overrides, cache, Q&A log
  runner.py              apply loop (stop at N, save after each job)
tests/                   unit + simulated-flow tests
```

## What changed from the original JobSailor

- Gemini integration was dead: it used `gemini-1.5-flash` (shut down by Google in Sept 2025) and returned `0` on any
  error. Rewritten on the `google-genai` SDK with fallbacks, retries, caching and your fixed answers.
- `apply_jobs.py` never counted applications (`applied` stayed 0), skipped *every* job through a bad `jdContainer`
  check, used a hard-coded absolute XPath for Save and hard-coded Windows paths. Rewritten.
- The runner overwrote `shortlisted_jobs.csv` on every run (and dropped the header). Replaced by an append-only history.
- Experience filter allowed `1-4`/`1-6` years; now strictly 0–3.
- No recency handling; now 24 h → 7 days, newest first.
- Search, filtering and applying were separate scripts; they are now one pipeline.

## License

MIT – see [LICENSE](LICENSE). Based on the original JobSailor by GoliathReaper.
