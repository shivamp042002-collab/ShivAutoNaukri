"""
JobSailor settings.  Edit this file to tune the bot.

Secrets (your Gemini API key) do NOT go here - put them in a `.env` file
(copy `.env.example` to `.env`).  Any value below can also be overridden from
`.env` using the same UPPER_CASE name, e.g.  MAX_APPLY_PER_RUN=30
"""
import os
from pathlib import Path

try:  # python-dotenv is optional but recommended
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _env(name, default, cast=str):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if cast is bool:
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    if cast is list:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return cast(raw)


# --------------------------------------------------------------------------
# Gemini (answers the questions Naukri asks after you click "Apply")
# --------------------------------------------------------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY", "")
# `gemini-flash-latest` is an alias that always points at a live Flash model.
# (The old `gemini-1.5-flash` was shut down by Google in Sept 2025.)
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-flash-latest")
# Tried in order when the main one is overloaded (503) or gone (404).  Lite models are usually less busy.
GEMINI_FALLBACK_MODELS = _env("GEMINI_FALLBACK_MODELS",
                              ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"], list)
GEMINI_TIMEOUT_SECONDS = _env("GEMINI_TIMEOUT_SECONDS", 20, int)              # per API call
GEMINI_MAX_SECONDS_PER_QUESTION = _env("GEMINI_MAX_SECONDS_PER_QUESTION", 60, int)  # give up on one question after this
PROFILE_PATH = Path(_env("PROFILE_PATH", str(BASE_DIR / "profile.json")))

# --------------------------------------------------------------------------
# How many jobs
# --------------------------------------------------------------------------
MAX_APPLY_PER_RUN = _env("MAX_APPLY_PER_RUN", 50, int)      # target successful applications per run
MAX_JOB_PAGES_TO_OPEN = _env("MAX_JOB_PAGES_TO_OPEN", 200, int)  # safety cap on job pages visited per run
MAX_RETRY_FAILED = _env("MAX_RETRY_FAILED", 2, int)          # a job that failed is retried at most this many times
SEARCH_PAGES_PER_QUERY = _env("SEARCH_PAGES_PER_QUERY", 3, int)

# --------------------------------------------------------------------------
# What jobs
# --------------------------------------------------------------------------
SEARCH_KEYWORDS = _env("SEARCH_KEYWORDS", [
    "SDE Intern",
    "Artificial Intelligence Engineer",
    "AI Engineer",
    "Implementation Engineer",
    "Technical Support",
    "IT application support",
    "Application support"
    "Software Developer",
    "Backend Developer",
    "Python Developer",
    "Django Developer",
    "Full Stack Developer",
    "Software Engineer",
    "API Developer",
   
    
], list)

# A job title must contain at least one of these words (whole-word match, case-insensitive)...
TITLE_MUST_CONTAIN_ANY = [
    "software", "developer", "backend", "back-end", "back end", "programmer", "SDE Intern", "SDE"
    "python", "django", "flask", "fastapi", "golang","Implementation engineer", "Technical support"
    "full stack", "full-stack", "fullstack", "sde", "api","qa", "tester", "testing", "devops",
    "Software Engineer", "Technical", "IT", "AI", "Artificial Intelligence"
]
# ...and must NOT contain any of these words.
TITLE_MUST_NOT_CONTAIN = [
    "senior", "sr", "lead", "principal", "manager", "architect", "head", "director", "staff",
    "sales", "business", "marketing", "seo", "content", "recruiter", "teacher", "executive",
    "bpo", "customer", "telecaller", "tele caller", "voice", "data entry", "analyst", "data scientist",
    "android", "ios", "mobile", "flutter", "php", "wordpress", "sap", "salesforce", "mainframe",
    "sharepoint", "oracle", "etl", "bi", "power bi", "embedded", "firmware", "vlsi", "hardware",
    "game", "unity", "quantum", "blockchain", "mechanical", "civil", "electrical",
]
BLACKLIST_COMPANIES = _env("BLACKLIST_COMPANIES", [], list)   # e.g. "Infosys,TCS"

# Experience window.  A job is accepted only if
#     min_required <= MAX_ALLOWED_MIN_EXPERIENCE   and   max_required <= MAX_ALLOWED_MAX_EXPERIENCE
# Default = "0-3 years" and "1-3 years" (and 0-1, 0-2, 1-2 ...), never above 3.
MAX_ALLOWED_MIN_EXPERIENCE = _env("MAX_ALLOWED_MIN_EXPERIENCE", 1, int)
MAX_ALLOWED_MAX_EXPERIENCE = _env("MAX_ALLOWED_MAX_EXPERIENCE", 3, int)
# Naukri's own "experience" search filter = your years of experience.  We search
# with each value so jobs of 0-1, 0-3, 1-3 ... all show up.
SEARCH_EXPERIENCE_VALUES = [int(x) for x in _env("SEARCH_EXPERIENCE_VALUES", ["1", "2"], list)]

# Recency: look at the last 24 hours FIRST, then widen to the last 7 days.
RECENCY_TIERS_DAYS = [1, 7]
MAX_JOB_AGE_DAYS = 7           # never apply to anything older than this
# Naukri "refreshes" old posts so the card says "posted today".  The first 6 digits of every job id are the real
# posting date (DDMMYY).  True = also reject jobs whose id-date is older than MAX_JOB_AGE_DAYS.
STRICT_JOB_ID_DATE = _env("STRICT_JOB_ID_DATE", True, bool)

# Optional: skip jobs whose description matches too few of your profile skills
# (0 = off).  Skills come from profile.json -> "skills".
MIN_MATCH_SCORE = _env("MIN_MATCH_SCORE", 0, int)

# --------------------------------------------------------------------------
# Files (all CSV / cache files live in ./data)
# --------------------------------------------------------------------------
APPLIED_CSV = DATA_DIR / "applied_jobs.csv"       # every job we tried + outcome (the "memory" between runs)
QA_LOG_CSV = DATA_DIR / "questions_answers.csv"   # every question Naukri asked + what we answered
ANSWER_CACHE = DATA_DIR / "answer_cache.json"     # so the same question never costs a second API call
LOG_FILE = DATA_DIR / "jobsailor.log"

# --------------------------------------------------------------------------
# Browser
# --------------------------------------------------------------------------
HEADLESS = _env("HEADLESS", False, bool)               # keep False - Naukri blocks headless more often
FIREFOX_BINARY = _env("FIREFOX_BINARY", "")            # blank = auto-detect
GECKODRIVER_PATH = _env("GECKODRIVER_PATH", "")        # blank = Selenium downloads it automatically
# Persistent Firefox profile so you only log in once.  Blank = ./data/firefox_profile
FIREFOX_PROFILE_DIR = Path(_env("FIREFOX_PROFILE_DIR", str(DATA_DIR / "firefox_profile")))
PAGE_LOAD_TIMEOUT = 30
MIN_DELAY, MAX_DELAY = 1.0, 3.0                        # random human-like pause between jobs (seconds)
MAX_QUESTIONS_PER_JOB = 15                             # give up on a job if the chatbot asks more than this