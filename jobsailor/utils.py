"""Small helpers: logging, URL/ID parsing, experience + posting-date parsing."""
import logging
import logging.handlers
import random
import re
import time
from datetime import date, datetime
from typing import Optional, Tuple
from urllib.parse import urlparse

# ---------------------------------------------------------------- logging


def setup_logging(log_file) -> logging.Logger:
    logger = logging.getLogger("jobsailor")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    try:
        fileh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fileh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
        logger.addHandler(fileh)
    except OSError:
        pass
    return logger


def human_pause(low: float, high: float) -> None:
    time.sleep(random.uniform(low, high))


# ---------------------------------------------------------------- URLs / IDs

_ID_RE = re.compile(r"-(\d{12})(?:$|[/?#])")


def clean_url(url: str) -> str:
    """Strip query string / fragment / trailing slash."""
    return (url or "").split("?")[0].split("#")[0].rstrip("/")


def absolute_url(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.naukri.com" + href
    return href


def job_id_from_url(url: str) -> Optional[str]:
    """Naukri URLs end with a 12-digit job id, e.g. ...-1-to-3-years-261026028027"""
    m = _ID_RE.search(clean_url(url) + "/")
    return m.group(1) if m else None


def job_key(url: str) -> str:
    """Stable key used for de-duplication between runs."""
    return job_id_from_url(url) or urlparse(clean_url(url)).path.lower()


def posted_date_from_id(job_id: Optional[str]) -> Optional[date]:
    """The first 6 digits of a Naukri job id are the posting date as DDMMYY."""
    if not job_id or len(job_id) != 12:
        return None
    try:
        return datetime.strptime(job_id[:6], "%d%m%y").date()
    except ValueError:
        return None


_AGE_RE = re.compile(r"(\d+)\s*\+?\s*(day|days|d)\b", re.I)


def age_days_from_text(text: str) -> Optional[int]:
    """'Just now', 'Few Hours Ago', '3 Days Ago', '30+ Days Ago' -> days (None if unknown)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if any(w in t for w in ("just now", "hour", "minute", "today", "few sec", "moment")):
        return 0
    m = _AGE_RE.search(t)
    if m:
        return int(m.group(1))
    if "yesterday" in t:
        return 1
    if "week" in t:
        m = re.search(r"(\d+)", t)
        return (int(m.group(1)) if m else 1) * 7
    return None


# ---------------------------------------------------------------- experience

_EXP_RANGE = re.compile(r"(\d+(?:\.\d+)?)[\s-]*(?:to|-|–)[\s-]*(\d+(?:\.\d+)?)[\s-]*(?:yrs?|years?)", re.I)
_EXP_PLUS = re.compile(r"(\d+(?:\.\d+)?)\s*\+\s*(?:yrs?|years?)", re.I)
_EXP_SINGLE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)[\s-]*(?:yrs?|years?)\b", re.I)


def parse_experience(*texts: str) -> Optional[Tuple[float, float]]:
    """Return (min_years, max_years) from the first text that contains one."""
    for text in texts:
        if not text:
            continue
        t = text.replace("_", "-")
        m = _EXP_RANGE.search(t)
        if m:
            return float(m.group(1)), float(m.group(2))
        m = _EXP_PLUS.search(t)
        if m:
            return float(m.group(1)), 99.0       # "5+ years" -> open ended
        if re.search(r"\bfreshers?\b", t, re.I):
            return 0.0, 0.0
        m = _EXP_SINGLE.search(t)
        if m:
            v = float(m.group(1))
            return v, v
    return None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()
