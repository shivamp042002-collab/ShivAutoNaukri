"""Finds candidate jobs on Naukri search pages: last-24-hours first, then last-7-days."""
import logging
import re
import time
from typing import Dict, List
from urllib.parse import quote

from bs4 import BeautifulSoup

import config
from .filters import Job, evaluate, prioritise
from .utils import absolute_url, clean_url, human_pause, job_key

log = logging.getLogger("jobsailor")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_search_url(keyword: str, page: int, experience: int, age_days: int) -> str:
    """e.g. https://www.naukri.com/backend-developer-jobs-2?k=backend%20developer&experience=2&jobAge=1"""
    path = f"{slugify(keyword)}-jobs" + (f"-{page}" if page > 1 else "")
    return (f"https://www.naukri.com/{path}?k={quote(keyword)}"
            f"&experience={experience}&jobAge={age_days}")


def _text(node, *selectors) -> str:
    for sel in selectors:
        el = node.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(" ", strip=True)
    return ""


def extract_jobs(html: str, search_tier_days: int) -> List[Job]:
    """Parse a Naukri search-results page into Job objects."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: Dict[str, Job] = {}

    cards = soup.select("div.srp-jobtuple-wrapper, div.cust-job-tuple, article.jobTuple")
    for card in cards:
        link = card.select_one("a.title, a[class*='title'], a[href*='job-listings-']")
        if not link or not link.get("href"):
            continue
        url = clean_url(absolute_url(link["href"]))
        if "job-listings-" not in url:
            continue
        jobs[url] = Job(
            url=url,
            title=link.get("title") or link.get_text(" ", strip=True),
            company=_text(card, "a.comp-name", "[class*='comp-name']", "[class*='subTitle']"),
            location=_text(card, "span.locWdth", "[class*='locWdth']", "[class*='location']"),
            experience_text=_text(card, "span.expwdth", "[class*='expwdth']", "[class*='experience']"),
            posted_text=_text(card, "span.job-post-day", "[class*='job-post-day']", "[class*='postedDate']"),
            search_tier_days=search_tier_days,
        )

    if not jobs:   # layout changed -> fall back to raw links (title + URL only)
        for a in soup.select("a[href*='job-listings-']"):
            url = clean_url(absolute_url(a.get("href", "")))
            title = a.get("title") or a.get_text(" ", strip=True)
            if "naukri.com" in url and title and url not in jobs:
                jobs[url] = Job(url=url, title=title, search_tier_days=search_tier_days)
    return list(jobs.values())


def collect_candidates(driver, tracker, target_pool: int, looks_blocked=None,
                       keywords=None, tiers=None) -> List[Job]:
    """Search tier by tier (24h -> 7d). Returns accepted, un-applied jobs ordered newest first."""
    keywords = keywords or config.SEARCH_KEYWORDS
    tiers = tiers or config.RECENCY_TIERS_DAYS
    accepted: Dict[str, Job] = {}
    rejected_reasons: Dict[str, int] = {}
    seen_urls = set()

    for tier_days in tiers:
        log.info("=== Searching jobs posted in the last %s ===", "24 hours" if tier_days == 1 else f"{tier_days} days")
        for keyword in keywords:
            for experience in config.SEARCH_EXPERIENCE_VALUES:
                for page in range(1, config.SEARCH_PAGES_PER_QUERY + 1):
                    url = build_search_url(keyword, page, experience, tier_days)
                    try:
                        driver.get(url)
                    except Exception as exc:  # noqa: BLE001 - timeouts etc.
                        log.warning("Could not load %s (%s)", url, str(exc)[:80])
                        break
                    time.sleep(3)
                    jobs = extract_jobs(driver.page_source, tier_days)
                    # Only treat the page as a captcha/block page when it has NO job cards at all.
                    if not jobs and looks_blocked and looks_blocked(driver):
                        log.error("Naukri is showing a captcha / block page. Solve it in the browser, "
                                  "then press Enter here to continue (or Ctrl+C to stop).")
                        input()
                        jobs = extract_jobs(driver.page_source, tier_days)
                    if not jobs:
                        break                       # no more pages for this query
                    new_here = 0
                    for job in jobs:
                        if job.url in seen_urls:
                            continue
                        seen_urls.add(job.url)
                        evaluate(job)
                        if job.reject_reason:
                            rejected_reasons[job.reject_reason.split(" (")[0]] = \
                                rejected_reasons.get(job.reject_reason.split(" (")[0], 0) + 1
                            continue
                        if tracker.should_skip(job.url):
                            rejected_reasons["already handled in an earlier run"] = \
                                rejected_reasons.get("already handled in an earlier run", 0) + 1
                            continue
                        if job.key not in accepted:
                            accepted[job.key] = job
                            new_here += 1
                    log.info("%-26s exp=%d p%d: %2d cards, %2d new eligible (pool %d)",
                             keyword, experience, page, len(jobs), new_here, len(accepted))
                    human_pause(1.5, 3.0)
                    if len(accepted) >= target_pool:
                        break
                    if new_here == 0:
                        break                       # later pages of this query rarely add anything new
                if len(accepted) >= target_pool:
                    break
            if len(accepted) >= target_pool:
                break
        # Enough fresh jobs already?  No need to widen the time window.
        if len(accepted) >= target_pool:
            log.info("Enough candidates (%d) - not widening the time window further.", len(accepted))
            break

    if rejected_reasons:
        top = sorted(rejected_reasons.items(), key=lambda kv: -kv[1])[:8]
        log.info("Filtered out: %s", "; ".join(f"{n}x {r}" for r, n in top))
    return prioritise(list(accepted.values()))