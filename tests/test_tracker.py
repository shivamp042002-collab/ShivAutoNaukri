import csv
import tempfile
import unittest
from pathlib import Path

from jobsailor.filters import Job, evaluate
from jobsailor.tracker import Tracker


def job(n, query=""):
    return evaluate(Job(url=f"https://www.naukri.com/job-listings-backend-developer-co{n}-pune-0-to-3-years-2610260{n:05d}{query}",
                        title="Backend Developer", company=f"Co{n}", experience_text="0-3 Yrs", posted_text="Just now"))


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "applied.csv"

    def tearDown(self):
        self.dir.cleanup()

    def test_second_run_skips_applied_jobs(self):
        t1 = Tracker(self.path)
        t1.record(job(1), "applied", questions=2)
        t1.record(job(2), "already_applied")
        t1.record(job(3), "expired")
        t2 = Tracker(self.path)                       # "second run"
        for n in (1, 2, 3):
            self.assertTrue(t2.should_skip(job(n).url), n)
        self.assertFalse(t2.should_skip(job(4).url))
        self.assertEqual(t2.total_applied, 1)

    def test_same_job_with_different_query_string_is_skipped(self):
        Tracker(self.path).record(job(1), "applied")
        self.assertTrue(Tracker(self.path).should_skip(job(1, "?src=similar").url))

    def test_failed_jobs_retried_then_given_up(self):
        t = Tracker(self.path, max_retry_failed=2)
        j = job(7)
        for _ in range(2):
            t.record(j, "failed", "boom")
            self.assertFalse(t.should_skip(j.url))
        t.record(j, "failed", "boom")                  # 3rd failure
        self.assertTrue(Tracker(self.path, max_retry_failed=2).should_skip(j.url))

    def test_csv_has_header_once_and_expected_columns(self):
        t = Tracker(self.path)
        t.record(job(1), "applied")
        t.record(job(2), "failed", "x")
        with self.path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "applied")
        self.assertEqual(rows[0]["company"], "Co1")
        self.assertIn("url", rows[0])

    def test_csv_written_immediately_survives_crash(self):
        Tracker(self.path).record(job(1), "applied")
        self.assertEqual(len(self.path.read_text(encoding="utf-8-sig").strip().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
