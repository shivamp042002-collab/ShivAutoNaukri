"""The apply loop: works through candidates (newest first) until the per-run target is reached."""
import logging
from collections import Counter, deque
from typing import Callable, Iterable

import config
from .applier import APPLIED, apply_to_job

log = logging.getLogger("jobsailor")


def run_applications(driver, candidates: Iterable, tracker, answerer, max_apply: int,
                     pause: Callable[[], None] = lambda: None, apply_fn=apply_to_job,
                     stats: Counter = None, source=None) -> Counter:
    """Apply until `max_apply` successful applications (or candidates / page budget run out).

    Every outcome is written to the CSV *immediately*, so a crash or Ctrl+C never loses progress, and a job
    handled in an earlier run is never opened again."""
    stats = Counter() if stats is None else stats      # caller may pass its own so Ctrl+C keeps the counts
    opened = 0
    fail_streak = 0
    queue = deque(candidates)
    while True:
        if stats[APPLIED] >= max_apply:
            break
        if not queue:
            # Ran out of jobs but not out of target: search DEEPER (later pages, more keywords) and carry on.
            if source is None or source.exhausted:
                break
            need = max_apply - stats[APPLIED]
            log.info("Only %d/%d applied and no jobs left in the queue - searching deeper...", stats[APPLIED], max_apply)
            queue.extend(source.fetch_more(max(20, int(need * 2.5))))
            continue
        job = queue.popleft()
        if opened >= config.MAX_JOB_PAGES_TO_OPEN:
            log.warning("Reached the safety cap of %d job pages for this run.", opened)
            break
        if tracker.should_skip(job.url):           # double-check against history
            stats["skipped_seen"] += 1
            continue
        opened += 1
        log.info("[%d/%d applied] %s | %s | %s | %s", stats[APPLIED], max_apply,
                 job.title, job.company, job.experience_text or "exp?", job.url.split("/")[-1])
        result = apply_fn(driver, job, answerer)
        tracker.record(job, result.status, result.detail, result.questions)
        stats[result.status] += 1
        fail_streak = fail_streak + 1 if result.status == "failed" else 0
        if fail_streak >= config.MAX_CONSECUTIVE_FAILURES:
            log.error("%d applications failed in a row - something is wrong (Naukri changed, Gemini key/quota, "
                      "or you were logged out). Stopping early; check data/debug/.", fail_streak)
            break
        log.info("   -> %s %s", result.status.upper(), result.detail)
        pause()
    return stats