"""The apply loop: works through candidates (newest first) until the per-run target is reached."""
import logging
from collections import Counter
from typing import Callable, Iterable

import config
from .applier import APPLIED, apply_to_job

log = logging.getLogger("jobsailor")


def run_applications(driver, candidates: Iterable, tracker, answerer, max_apply: int,
                     pause: Callable[[], None] = lambda: None, apply_fn=apply_to_job,
                     stats: Counter = None) -> Counter:
    """Apply until `max_apply` successful applications (or candidates / page budget run out).

    Every outcome is written to the CSV *immediately*, so a crash or Ctrl+C never loses progress, and a job
    handled in an earlier run is never opened again."""
    stats = Counter() if stats is None else stats      # caller may pass its own so Ctrl+C keeps the counts
    opened = 0
    for job in candidates:
        if stats[APPLIED] >= max_apply:
            break
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
        log.info("   -> %s %s", result.status.upper(), result.detail)
        pause()
    return stats
