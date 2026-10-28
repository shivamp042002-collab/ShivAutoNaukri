"""CSV memory of every job we touched, so a second run never repeats work."""
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict

import config
from .utils import job_key

log = logging.getLogger("jobsailor")

FIELDS = ["timestamp", "status", "job_id", "title", "company", "location", "experience",
          "posted_age_days", "match_score", "questions_answered", "detail", "url"]

# These outcomes are final - never open the job again.
FINAL_STATUSES = {"applied", "already_applied", "external_site", "expired", "low_match"}
APPLIED_STATUSES = {"applied"}


class Tracker:
    def __init__(self, path: Path = None, max_retry_failed: int = None):
        self.path = Path(path or config.APPLIED_CSV)
        self.max_retry = config.MAX_RETRY_FAILED if max_retry_failed is None else max_retry_failed
        self.final: set = set()
        self.fail_count: Dict[str, int] = {}
        self.total_applied = 0
        self._load()

    # ---------------------------------------------------------------- reading
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    key = job_key(row.get("url", "")) if row.get("url") else row.get("job_id", "")
                    if not key:
                        continue
                    status = (row.get("status") or "").strip()
                    if status in FINAL_STATUSES:
                        self.final.add(key)
                    elif status == "failed":
                        self.fail_count[key] = self.fail_count.get(key, 0) + 1
                    if status in APPLIED_STATUSES:
                        self.total_applied += 1
        except (OSError, csv.Error) as exc:
            log.warning("Could not read %s (%s) - starting with empty history", self.path, exc)

    def should_skip(self, url: str) -> bool:
        key = job_key(url)
        if key in self.final:
            return True
        return self.fail_count.get(key, 0) > self.max_retry

    def already_applied(self, url: str) -> bool:
        return job_key(url) in self.final

    # ---------------------------------------------------------------- writing
    def record(self, job, status: str, detail: str = "", questions: int = 0) -> None:
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "job_id": job.job_id or "",
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "experience": job.experience_text or "",
            "posted_age_days": "" if job.age_days is None else job.age_days,
            "match_score": job.match_score,
            "questions_answered": questions,
            "detail": detail,
            "url": job.url,
        }
        key = job_key(job.url)
        if status in FINAL_STATUSES:
            self.final.add(key)
        elif status == "failed":
            self.fail_count[key] = self.fail_count.get(key, 0) + 1
        if status in APPLIED_STATUSES:
            self.total_applied += 1
        self._append(row)

    def _append(self, row: dict) -> None:
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        try:
            with self.path.open("a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if new_file:
                    w.writeheader()
                w.writerow(row)
        except PermissionError:
            # Usually: the CSV is open in Excel.  Do not lose the record.
            backup = self.path.with_name(self.path.stem + "_pending.csv")
            log.warning("%s is locked (open in Excel?). Saving this row to %s instead.", self.path.name, backup.name)
            write_header = not backup.exists()
            with backup.open("a", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if write_header:
                    w.writeheader()
                w.writerow(row)
