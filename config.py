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
# Flash-Lite models are the fastest and have the friendliest free-tier limits - plenty for form questions.
# (The old `gemini-1.5-flash` was shut down by Google in Sept 2025.)
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Tried in order when the main one is rate-limited (429), overloaded (503) or gone (404).
GEMINI_FALLBACK_MODELS = _env("GEMINI_FALLBACK_MODELS",
                              ["gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"], list)
GEMINI_TIMEOUT_SECONDS = _env("GEMINI_TIMEOUT_SECONDS", 12, int)                    # per API call
GEMINI_MAX_SECONDS_PER_QUESTION = _env("GEMINI_MAX_SECONDS_PER_QUESTION", 25, int)  # give up on one question after this
PROFILE_PATH = Path(_env("PROFILE_PATH", str(BASE_DIR / "profile.json")))

# --------------------------------------------------------------------------
# How many jobs
# --------------------------------------------------------------------------
MAX_APPLY_PER_RUN = _env("MAX_APPLY_PER_RUN", 70, int)      # target successful applications per run
MAX_JOB_PAGES_TO_OPEN = _env("MAX_JOB_PAGES_TO_OPEN", 400, int)  # safety cap on job pages visited per run
MAX_RETRY_FAILED = _env("MAX_RETRY_FAILED", 2, int)          # a job that failed is retried at most this many times
SEARCH_PAGES_PER_QUERY = _env("SEARCH_PAGES_PER_QUERY", 3, int)   # round 1: pages 1..3 of every keyword
SEARCH_DEEP_PAGES = _env("SEARCH_DEEP_PAGES", 8, int)           # round 2 goes down to this page
SEARCH_DEEPEST_PAGES = _env("SEARCH_DEEPEST_PAGES", 15, int)    # round 3 goes down to this page
SEARCH_DRY_PAGES_STOP = _env("SEARCH_DRY_PAGES_STOP", 3, int)   # stop a query after this many pages with nothing new
MAX_CONSECUTIVE_FAILURES = _env("MAX_CONSECUTIVE_FAILURES", 12, int)  # stop early if Naukri/Gemini is clearly broken

# --------------------------------------------------------------------------
# What jobs
# --------------------------------------------------------------------------
# "fresher" = you have 0 years of experience  ->  searches Naukri's "0 years" filter, adds fresher-style keywords and
# allows "Trainee" roles.   "experienced" = 1-3 years.
CANDIDATE_LEVEL = _env("CANDIDATE_LEVEL", "fresher")
FRESHER = CANDIDATE_LEVEL.strip().lower().startswith("fresh")
ALLOW_INTERNSHIPS = _env("ALLOW_INTERNSHIPS", False, bool)    # internships are usually short & stipend-only

# Wide net: any tech role a fresher can do.  (Java / PHP / .NET / React / Spring Boot are excluded in the title
# filter below, so they are not searched for.)
_BASE_KEYWORDS = [
    "Python Developer", "Software Developer", "Software Engineer", "Backend Developer",
    "Application Support Engineer", "Technical Support Engineer", "Implementation Engineer",
    "Production Support Engineer", "Software Support Engineer", "Associate Software Engineer",
    "Django Developer", "Data Engineer", "Automation Engineer",
    "Test Engineer", "QA Engineer", "DevOps Engineer", "Cloud Support Engineer", "SQL Developer",
    "Full Stack Developer", "Web Developer", "Solutions Engineer", "Systems Engineer", "IT Support Engineer",
    "Technical Associate", "API Developer", "Integration Engineer",
]
_FRESHER_KEYWORDS = [
    "Fresher Software Developer", "Trainee Software Engineer", "Junior Software Developer",
    "Software Developer Trainee", "Graduate Software Engineer", "Junior Python Developer",
    "Entry Level Software Engineer", "Fresher Python Developer", "Fresher Application Support Engineer",
]
# Fresher keywords go FIRST so they get the best use of the per-run page budget.
SEARCH_KEYWORDS = _env("SEARCH_KEYWORDS", (_FRESHER_KEYWORDS if FRESHER else []) + _BASE_KEYWORDS, list)
# Used only in the deeper search rounds, when the first rounds did not give enough jobs.
EXTRA_KEYWORDS = _env("EXTRA_KEYWORDS", [
    "Software Engineer Trainee", "Application Developer", "Python Backend Developer", "Golang Developer",
    "Programmer", "SDE 1", "Software Engineer 1", "Backend Engineer", "Junior Backend Developer",
    "Flask Developer", "FastAPI Developer", "Associate Software Developer", "Software Trainee",
    "Technical Support Executive", "L1 Support Engineer", "L2 Support Engineer", "Application Engineer",
    "Customer Success Engineer", "Technical Consultant", "ETL Developer", "Big Data Engineer",
    "Machine Learning Engineer", "AI Engineer", "Python Automation Engineer", "Cloud Engineer", "AWS Engineer",
    "Linux Administrator", "System Administrator", "Database Administrator", "Support Analyst",
    "Product Support Engineer", "Technical Trainee", "Web Application Developer",
], list)

# A job title must contain at least one of these (whole word / phrase, case-insensitive)...
TITLE_MUST_CONTAIN_ANY = [
    "software", "developer", "programmer", "backend", "back-end", "back end", "python", "django", "flask",
    "fastapi", "node", "golang", "full stack", "full-stack", "fullstack", "sde", "api", "web",
    "implementation", "integration", "application support", "application engineer", "technical support",
    "support engineer", "support analyst", "it support", "technical associate", "technical consultant",
    "solutions engineer", "systems engineer", "system engineer", "system administrator", "linux", "cloud",
    "devops", "aws", "qa", "test engineer", "tester", "testing", "automation", "sql", "database",
    "data engineer", "data analyst", "etl", "big data", "machine learning", "ai engineer", "l1", "l2",
    "production support", "software trainee", "technical trainee", "noc",
]
# ...and must NOT contain any of these words.
# 1) Stacks you do NOT want:  java, php, .net, react, spring boot   (edit here or EXCLUDED_TECH in .env)
EXCLUDED_TECH = _env("EXCLUDED_TECH", [
    "java", "j2ee", "jsp", "hibernate", "spring", "springboot", "php", "laravel", ".net", "dotnet", "asp.net",
    "vb.net", "c#", "react", "reactjs", "react.js", "react native",
], list)
# 2) Not tech / too senior / not a fit
TITLE_MUST_NOT_CONTAIN = EXCLUDED_TECH + [
    "senior", "sr", "lead", "principal", "manager", "architect", "head", "director", "staff",
    "sales", "business", "marketing", "seo", "content", "recruiter", "teacher", "hr", "accounts", "accountant",
    "finance", "financial", "admin", "receptionist", "driver", "warehouse", "logistics",
    "bpo", "customer", "telecaller", "tele caller", "voice", "non voice", "non-voice", "data entry",
    "chat support", "email support", "process associate", "wordpress", "sap", "salesforce", "mainframe",
    "sharepoint", "embedded", "firmware", "vlsi", "hardware", "game", "unity", "quantum",
    "mechanical", "civil", "electrical", "electronics", "chemical", "production engineer", "site engineer",
    "field engineer", "service engineer", "maintenance", "instrumentation", "automobile", "textile",
] + ([] if ALLOW_INTERNSHIPS else ["intern", "internship"]) + ([] if FRESHER else ["trainee", "fresher batch"])
BLACKLIST_COMPANIES = _env("BLACKLIST_COMPANIES", [], list)   # e.g. "Infosys,TCS"

# Experience window.  A job is accepted only if
#     min_required <= MAX_ALLOWED_MIN_EXPERIENCE   and   max_required <= MAX_ALLOWED_MAX_EXPERIENCE
# Default = "0-3 years" and "1-3 years" (and 0-1, 0-2, 1-2 ...), never above 3.
MAX_ALLOWED_MIN_EXPERIENCE = _env("MAX_ALLOWED_MIN_EXPERIENCE", 1, int)
MAX_ALLOWED_MAX_EXPERIENCE = _env("MAX_ALLOWED_MAX_EXPERIENCE", 3, int)
# Naukri's own "experience" search filter = YOUR years of experience.  Fresher -> 0 and 1, so jobs of
# 0-1, 0-2, 0-3 and 1-3 all show up.
SEARCH_EXPERIENCE_VALUES = [int(x) for x in _env("SEARCH_EXPERIENCE_VALUES", ["0", "1"] if FRESHER else ["1", "2"], list)]

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
MIN_DELAY, MAX_DELAY = 2.0, 5.0                        # random human-like pause between jobs (seconds)
MAX_QUESTIONS_PER_JOB = 15                             # give up on a job if the chatbot asks more than this
MAX_SECONDS_PER_JOB = 180                              # hard time limit for one application
DEBUG_DIR = DATA_DIR / "debug"                         # page dumps + screenshots of failed applications