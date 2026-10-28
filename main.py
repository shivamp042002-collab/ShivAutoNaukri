#!/usr/bin/env python3
"""JobSailor - auto-apply to recent Naukri jobs (0-3 yrs experience) and answer questions with Gemini.

Usage:
    python main.py                 # normal run (applies to up to 50 jobs)
    python main.py --dry-run       # search + filter only, apply to nothing
    python main.py --max 20        # apply to at most 20 jobs this run
    python main.py --stats         # show a summary of data/applied_jobs.csv and exit
"""
import argparse
import csv
import json
import sys
from collections import Counter

import config
from jobsailor.tracker import Tracker
from jobsailor.utils import human_pause, setup_logging


def load_profile() -> dict:
    if not config.PROFILE_PATH.exists():
        sys.exit(f"\n[!] {config.PROFILE_PATH.name} not found.\n"
                 f"    Copy profile.example.json to profile.json and fill in your details.")
    try:
        return json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))
    except ValueError as exc:
        sys.exit(f"\n[!] {config.PROFILE_PATH.name} is not valid JSON: {exc}")


def show_stats() -> None:
    if not config.APPLIED_CSV.exists():
        print("No history yet - run the bot first.")
        return
    with config.APPLIED_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    by_status = Counter(r["status"] for r in rows)
    by_day = Counter(r["timestamp"][:10] for r in rows if r["status"] == "applied")
    print(f"\nHistory file: {config.APPLIED_CSV}")
    print(f"Total rows  : {len(rows)}")
    for status, n in by_status.most_common():
        print(f"  {status:<16}{n}")
    if by_day:
        print("\nApplications per day:")
        for day in sorted(by_day)[-10:]:
            print(f"  {day}  {by_day[day]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Naukri auto-apply bot")
    ap.add_argument("--dry-run", action="store_true", help="find and filter jobs but do not apply")
    ap.add_argument("--max", type=int, default=None, help=f"jobs to apply to this run (default {config.MAX_APPLY_PER_RUN})")
    ap.add_argument("--headless", action="store_true", help="run Firefox without a window (not recommended)")
    ap.add_argument("--keywords", type=str, default=None, help='override search keywords, comma separated')
    ap.add_argument("--stats", action="store_true", help="print summary of previous runs and exit")
    args = ap.parse_args()

    if args.stats:
        show_stats()
        return 0

    log = setup_logging(config.LOG_FILE)
    max_apply = args.max or config.MAX_APPLY_PER_RUN
    profile = {} if args.dry_run and not config.PROFILE_PATH.exists() else load_profile()

    if not args.dry_run and not config.GEMINI_API_KEY:
        sys.exit("\n[!] GEMINI_API_KEY is missing.\n"
                 "    Copy .env.example to .env and paste your key "
                 "(free key: https://aistudio.google.com/apikey).")

    # Heavy imports (selenium) only after the cheap checks above
    from jobsailor.runner import run_applications
    from jobsailor.browser import ensure_logged_in, looks_blocked, make_driver
    from jobsailor.gemini_client import GeminiAnswerer
    from jobsailor.search import collect_candidates

    tracker = Tracker()
    answerer = GeminiAnswerer(config.GEMINI_API_KEY, profile)
    log.info("History: %d jobs applied in earlier runs. Target this run: %d.", tracker.total_applied, max_apply)

    keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else None
    driver = make_driver(headless=args.headless)
    stats = Counter()
    try:
        if not ensure_logged_in(driver):
            log.error("Login not confirmed - stopping.")
            return 1

        pool_target = int(max_apply * 1.5) + 5   # collect extra: some will be expired / external / fail
        candidates = collect_candidates(driver, tracker, pool_target, looks_blocked, keywords=keywords)
        log.info("Candidates ready: %d (newest first)", len(candidates))

        if args.dry_run:
            out = config.DATA_DIR / "dry_run_candidates.csv"
            with out.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["tier", "age_days", "title", "company", "experience", "location", "url"])
                for j in candidates:
                    w.writerow([j.tier, j.age_days, j.title, j.company, j.experience_text, j.location, j.url])
            log.info("Dry run finished - %d candidates written to %s", len(candidates), out)
            return 0

        run_applications(driver, candidates, tracker, answerer, max_apply, stats=stats,
                         pause=lambda: human_pause(config.MIN_DELAY, config.MAX_DELAY))

    except KeyboardInterrupt:
        log.warning("Stopped by user. Progress so far is saved.")
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass

    print("\n" + "=" * 46)
    print(" RUN SUMMARY")
    print("=" * 46)
    print(f" Applied this run     : {stats['applied']} / {max_apply}")
    for k in ("already_applied", "external_site", "expired", "low_match", "failed"):
        if stats[k]:
            print(f" {k.replace('_', ' ').capitalize():<21}: {stats[k]}")
    print(f" Gemini API calls     : {answerer.calls}")
    print(f" All-time applied     : {tracker.total_applied}")
    print(f" Details              : {config.APPLIED_CSV}")
    if stats["applied"] < max_apply:
        print(f"\n Only {stats['applied']} of {max_apply} reached - not enough fresh matching jobs. Run again later "
              f"or add more SEARCH_KEYWORDS in config.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())