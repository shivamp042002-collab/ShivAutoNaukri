import tempfile
import unittest
from pathlib import Path

from tests import _selenium_stub
_selenium_stub.install()

from jobsailor.applier import ApplyResult  # noqa: E402
from jobsailor.filters import Job, evaluate, prioritise  # noqa: E402
from jobsailor.runner import run_applications  # noqa: E402
from jobsailor.tracker import Tracker  # noqa: E402


def jobs(n):
    out = []
    for i in range(n):
        out.append(evaluate(Job(
            url=f"https://www.naukri.com/job-listings-backend-developer-co{i}-pune-0-to-3-years-27102600{i:04d}",
            title="Backend Developer", company=f"Co{i}", experience_text="0-3 Yrs",
            posted_text="Just now" if i % 2 == 0 else "3 Days Ago")))
    return prioritise(out)


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.csv = Path(self.tmp.name) / "applied.csv"
        self.opened = []

    def fake_apply(self, driver, job, answerer):
        self.opened.append(job.url)
        n = int(job.company[2:])
        if n % 10 == 3: return ApplyResult("expired", "gone")
        if n % 10 == 6: return ApplyResult("external_site", "company site")
        if n % 10 == 9: return ApplyResult("failed", "boom")
        return ApplyResult("applied", "", 1)

    def test_stops_at_50_and_second_run_never_repeats(self):
        cands = jobs(200)
        t1 = Tracker(self.csv)
        s1 = run_applications(None, cands, t1, None, 50, apply_fn=self.fake_apply)
        self.assertEqual(s1["applied"], 50)
        first_run = set(self.opened); self.opened.clear()

        t2 = Tracker(self.csv)                                  # fresh process = second run
        s2 = run_applications(None, cands, t2, None, 50, apply_fn=self.fake_apply)
        self.assertEqual(s2["applied"], 50)
        second_run = set(self.opened)

        applied_first = {u for u in first_run if int(u.split("/")[-1].split("-co")[1].split("-")[0]) % 10 not in (3, 6, 9)}
        self.assertFalse(applied_first & second_run, "a job applied in run 1 was opened again in run 2")
        self.assertEqual(Tracker(self.csv).total_applied, 100)

    def test_newest_first_order_is_preserved(self):
        run_applications(None, jobs(20), Tracker(self.csv), None, 5, apply_fn=self.fake_apply)
        ages = [0 if "Co" in u and int(u.split("-co")[1].split("-")[0]) % 2 == 0 else 3 for u in self.opened]
        self.assertEqual(ages, sorted(ages))

    def test_fewer_candidates_than_target_is_fine(self):
        s = run_applications(None, jobs(5), Tracker(self.csv), None, 50, apply_fn=self.fake_apply)
        self.assertEqual(sum(s.values()), 5)

    def test_every_attempt_saved_to_csv(self):
        run_applications(None, jobs(12), Tracker(self.csv), None, 50, apply_fn=self.fake_apply)
        lines = self.csv.read_text(encoding="utf-8-sig").strip().splitlines()
        self.assertEqual(len(lines), 13)                        # header + 12


if __name__ == "__main__":
    unittest.main()


class CtrlC(unittest.TestCase):
    def test_counts_survive_keyboard_interrupt(self):
        from collections import Counter
        calls = {"n": 0}

        def apply_fn(driver, job, answerer):
            calls["n"] += 1
            if calls["n"] == 4:
                raise KeyboardInterrupt
            return ApplyResult("applied", "", 0)

        with tempfile.TemporaryDirectory() as d:
            stats = Counter()
            with self.assertRaises(KeyboardInterrupt):
                run_applications(None, jobs(10), Tracker(Path(d) / "a.csv"), None, 50, apply_fn=apply_fn, stats=stats)
            self.assertEqual(stats["applied"], 3)
            self.assertEqual(Tracker(Path(d) / "a.csv").total_applied, 3)
