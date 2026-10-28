"""Decides whether a job is worth applying to, and in which order."""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

import config
from .utils import (age_days_from_text, clean_url, job_id_from_url, job_key,
                    normalize, parse_experience, posted_date_from_id)


@dataclass
class Job:
    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    experience_text: str = ""
    posted_text: str = ""
    search_tier_days: int = 7          # which recency search (1 = last 24h, 7 = last week) found it
    # filled in by evaluate()
    job_id: Optional[str] = None
    experience: Optional[Tuple[float, float]] = None
    age_days: Optional[int] = None
    tier: int = 99                     # 0 = last 24h, 1 = last 7 days  (lower is applied first)
    reject_reason: str = ""
    match_score: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return job_key(self.url)


def experience_label(exp: Optional[Tuple[float, float]]) -> str:
    if not exp:
        return "unknown"
    lo, hi = exp
    fmt = lambda v: str(int(v)) if float(v).is_integer() else str(v)
    return f"{fmt(lo)}-{fmt(hi)} years"


def experience_ok(exp: Optional[Tuple[float, float]]) -> Tuple[bool, str]:
    if exp is None:
        return False, "experience not found"
    lo, hi = exp
    if lo > config.MAX_ALLOWED_MIN_EXPERIENCE:
        return False, f"needs {experience_label(exp)} (min above {config.MAX_ALLOWED_MIN_EXPERIENCE})"
    if hi > config.MAX_ALLOWED_MAX_EXPERIENCE:
        return False, f"needs {experience_label(exp)} (max above {config.MAX_ALLOWED_MAX_EXPERIENCE})"
    return True, ""


def _has_word(text: str, token: str) -> bool:
    """Whole-word match: 'qa' is not found in 'squad', 'intern' not in 'international'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(normalize(token)) + r"(?![a-z0-9])", text) is not None


def title_ok(title: str) -> Tuple[bool, str]:
    t = normalize(title)
    if not t:
        return False, "empty title"
    if t.count("/") >= 3 or t.count("|") >= 3 or len(t) > 100:
        return False, "keyword-stuffed title"
    for bad in config.TITLE_MUST_NOT_CONTAIN:
        if _has_word(t, bad):
            return False, f"title contains '{bad}'"
    if not any(_has_word(t, good) for good in config.TITLE_MUST_CONTAIN_ANY):
        return False, "title is not a developer role"
    return True, ""


def company_ok(company: str) -> Tuple[bool, str]:
    c = normalize(company)
    for bad in config.BLACKLIST_COMPANIES:
        if normalize(bad) and normalize(bad) in c:
            return False, f"blacklisted company '{bad}'"
    return True, ""


def recency(job: Job, today: Optional[date] = None) -> Tuple[Optional[int], int]:
    """Return (age_in_days, tier).  Tier 0 = last 24h, 1 = last 7 days, 99 = too old.

    Two signals: the card text ("2 Days Ago") and the date inside the job id.  Naukri refreshes old posts, so the
    card can say "Just now" for a job posted months ago - with STRICT_JOB_ID_DATE the OLDER of the two wins."""
    today = today or date.today()
    card_age = age_days_from_text(job.posted_text)
    posted = posted_date_from_id(job.job_id)
    id_age = max((today - posted).days, 0) if posted else None

    if card_age is not None and id_age is not None:
        age = max(card_age, id_age) if config.STRICT_JOB_ID_DATE else card_age
    elif card_age is not None:
        age = card_age
    elif id_age is not None:
        age = id_age
    else:
        age = job.search_tier_days                        # trust the search filter we used
    if age <= 1:
        return age, 0
    if age <= config.MAX_JOB_AGE_DAYS:
        return age, 1
    return age, 99


def evaluate(job: Job, today: Optional[date] = None) -> Job:
    """Fill derived fields and set job.reject_reason ('' = accepted)."""
    job.url = clean_url(job.url)
    job.job_id = job_id_from_url(job.url)
    job.experience = parse_experience(job.experience_text, job.url)
    job.age_days, job.tier = recency(job, today)
    job.reject_reason = ""

    for check in (title_ok(job.title), company_ok(job.company), experience_ok(job.experience)):
        if not check[0]:
            job.reject_reason = check[1]
            return job
    if job.tier == 99:
        job.reject_reason = f"too old ({job.age_days} days)"
    return job


def prioritise(jobs: List[Job]) -> List[Job]:
    """Newest first: last-24h jobs, then last-7-days jobs; newer day first inside each tier."""
    return sorted(jobs, key=lambda j: (j.tier, j.age_days if j.age_days is not None else 99))


def description_match_score(description: str, skills: List[str]) -> int:
    """% of the profile's skills that appear in the job description (0-100)."""
    skills = [normalize(s) for s in skills if s]
    if not skills:
        return 100
    text = normalize(description)
    hit = sum(1 for s in skills if s in text)
    return round(hit / len(skills) * 100)