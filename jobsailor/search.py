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


CARDS_WAIT_TIMEOUT = 10.0


def _load_jobs(driver, search_tier_days: int, timeout: float = None) -> List["Job"]:
    """Wait until the page has REAL, parseable job cards and return them (empty list if none appear in time).

    Do not just look for the text 'job-listings-' in the page source: Naukri puts it in an embedded data blob long
    before the cards are drawn, so that check returns too early and every page looks empty."""
    end = time.time() + (CARDS_WAIT_TIMEOUT if timeout is None else timeout)
    while True:
        try:
            jobs = extract_jobs(driver.page_source, search_tier_days)
        except Exception:  # noqa: BLE001 - page changing under us
            jobs = []
        if jobs or time.time() >= end:
            return jobs
        time.sleep(0.4)


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


class CandidateSource:
    """Finds jobs in rounds so the bot never runs dry before it reaches its target.

    Round 1 = first pages of every keyword (24 h, then 7 days).  If the apply loop uses everything up and still
    needs more successful applications, `fetch_more()` goes DEEPER (later result pages, extra keywords).  Jobs
    already returned, already applied, or filtered out are never returned again."""

    def __init__(self, driver, tracker, looks_blocked=None, keywords=None, tiers=None, rounds=None):
        self.driver = driver
        self.tracker = tracker
        self.looks_blocked = looks_blocked
        self.tiers = tiers or config.RECENCY_TIERS_DAYS
        base = keywords or config.SEARCH_KEYWORDS
        extra = [] if keywords else [k for k in getattr(config, "EXTRA_KEYWORDS", []) if k not in base]
        # (first page, last page, keywords) for each round
        self.rounds = rounds or [
            (1, config.SEARCH_PAGES_PER_QUERY, list(base)),
            (config.SEARCH_PAGES_PER_QUERY + 1, config.SEARCH_DEEP_PAGES, list(base) + extra),
            (config.SEARCH_DEEP_PAGES + 1, config.SEARCH_DEEPEST_PAGES, list(base) + extra),
        ]
        self.round_no = 0
        self.seen_urls = set()
        self.handed_out = set()
        self.rejected: Dict[str, int] = {}

    @property
    def exhausted(self) -> bool:
        return self.round_no >= len(self.rounds)

    def _reject(self, reason: str) -> None:
        reason = reason.split(" (")[0]
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    def _search_pass(self, tier_days, keywords, first_page, last_page, found, target) -> None:
        for keyword in keywords:
            for experience in config.SEARCH_EXPERIENCE_VALUES:
                dry_pages = 0
                for page in range(first_page, last_page + 1):
                    url = build_search_url(keyword, page, experience, tier_days)
                    try:
                        self.driver.get(url)
                    except Exception as exc:  # noqa: BLE001 - timeouts etc.
                        log.warning("Could not load %s (%s)", url, str(exc)[:80])
                        break
                    jobs = _load_jobs(self.driver, tier_days)
                    # Only treat the page as a captcha/block page when it has NO job cards at all.
                    if not jobs and self.looks_blocked and self.looks_blocked(self.driver):
                        log.error("Naukri is showing a captcha / block page. Solve it in the browser, "
                                  "then press Enter here to continue (or Ctrl+C to stop).")
                        input()
                        jobs = _load_jobs(self.driver, tier_days)
                    if not jobs:
                        if page == first_page == 1:     # never fail silently: say so
                            try:
                                title = self.driver.title
                            except Exception:  # noqa: BLE001
                                title = "?"
                            log.warning("%-26s exp=%d: NO job cards loaded (page title: %r)", keyword, experience, title)
                        break                           # ran out of result pages for this query
                    new_here = 0
                    for job in jobs:
                        if job.url in self.seen_urls:
                            continue
                        self.seen_urls.add(job.url)
                        evaluate(job)
                        if job.reject_reason:
                            self._reject(job.reject_reason)
                            continue
                        if self.tracker.should_skip(job.url):
                            self._reject("already handled in an earlier run")
                            continue
                        if job.key not in found and job.key not in self.handed_out:
                            found[job.key] = job
                            new_here += 1
                    log.info("%-26s exp=%d p%-2d: %2d cards, %2d new eligible (pool %d)",
                             keyword, experience, page, len(jobs), new_here, len(found))
                    human_pause(0.6, 1.4)
                    if len(found) >= target:
                        return
                    # Earlier pages are full of jobs we already applied to; keep going deeper until a query
                    # has produced nothing new for several pages in a row.
                    dry_pages = 0 if new_here else dry_pages + 1
                    if dry_pages >= config.SEARCH_DRY_PAGES_STOP:
                        break

    def fetch_more(self, target: int) -> List[Job]:
        """Run search rounds until `target` NEW eligible jobs are found (or every round is used up)."""
        found: Dict[str, Job] = {}
        while len(found) < target and not self.exhausted:
            first, last, keywords = self.rounds[self.round_no]
            self.round_no += 1
            log.info("--- Search round %d/%d: result pages %d-%d, %d keywords ---",
                     self.round_no, len(self.rounds), first, last, len(keywords))
            for tier_days in self.tiers:
                log.info("=== Jobs posted in the last %s ===", "24 hours" if tier_days == 1 else f"{tier_days} days")
                self._search_pass(tier_days, keywords, first, last, found, target)
                if len(found) >= target:
                    break
        if self.rejected:
            top = sorted(self.rejected.items(), key=lambda kv: -kv[1])[:8]
            log.info("Filtered out so far: %s", "; ".join(f"{n}x {r}" for r, n in top))
        out = prioritise(list(found.values()))
        self.handed_out.update(j.key for j in out)
        return out


def collect_candidates(driver, tracker, target_pool: int, looks_blocked=None,
                       keywords=None, tiers=None) -> List[Job]:
    """One-shot search (round 1 only). Returns accepted, un-applied jobs ordered newest first."""
    src = CandidateSource(driver, tracker, looks_blocked, keywords, tiers)
    src.rounds = src.rounds[:1]
    return src.fetch_more(target_pool)