import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from jobsailor import search
from jobsailor.filters import evaluate
from jobsailor.tracker import Tracker


def card(slug, title, exp, posted, company="Acme", loc="Pune"):
    return f"""
    <div class="srp-jobtuple-wrapper">
      <a class="title" href="https://www.naukri.com/job-listings-{slug}?src=x" title="{title}">{title}</a>
      <a class="comp-name">{company}</a>
      <span class="expwdth">{exp}</span><span class="locWdth">{loc}</span>
      <span class="job-post-day">{posted}</span>
    </div>"""


def page(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


class ExtractTests(unittest.TestCase):
    def test_extract_cards(self):
        html = page(card("backend-developer-acme-pune-0-to-3-years-271026000001", "Backend Developer", "0-3 Yrs", "2 Days Ago"))
        (j,) = search.extract_jobs(html, 7)
        self.assertEqual((j.title, j.company, j.experience_text, j.location, j.posted_text),
                         ("Backend Developer", "Acme", "0-3 Yrs", "Pune", "2 Days Ago"))
        self.assertFalse(j.url.endswith("?src=x"))

    def test_fallback_when_layout_changes(self):
        html = '<a href="/job-listings-python-developer-x-pune-0-to-2-years-271026000009">Python Developer</a>'
        (j,) = search.extract_jobs(html, 1)
        self.assertEqual(j.title, "Python Developer")
        self.assertTrue(j.url.startswith("https://www.naukri.com/job-listings-"))

    def test_search_url(self):
        u = search.build_search_url("Backend Developer", 2, 1, 7)
        self.assertEqual(u, "https://www.naukri.com/backend-developer-jobs-2?k=Backend%20Developer&experience=1&jobAge=7")


class FakeDriver:
    """Returns a different results page depending on the jobAge value in the URL."""
    def __init__(self, by_age):
        self.by_age, self.page_source, self.urls = by_age, "", []
    def get(self, url):
        self.urls.append(url)
        age = int(url.split("jobAge=")[1])
        page_no = int(url.split("-jobs-")[1].split("?")[0]) if "-jobs-" in url else 1
        self.page_source = self.by_age.get(age, "") if page_no == 1 else ""


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tracker = Tracker(Path(self.tmp.name) / "a.csv")
        for obj, attr in ((search.time, "sleep"), (search, "human_pause")):
            p = mock.patch.object(obj, attr, lambda *_: None)
            p.start(); self.addCleanup(p.stop)
        for name, val in (("SEARCH_KEYWORDS", ["Backend Developer"]), ("SEARCH_EXPERIENCE_VALUES", [1]),
                          ("SEARCH_PAGES_PER_QUERY", 2)):
            p = mock.patch.object(config, name, val)
            p.start(); self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def pages(self):
        fresh = page(
            card("backend-developer-a-pune-0-to-3-years-271026000001", "Backend Developer", "0-3 Yrs", "Few Hours Ago", "A"),
            card("senior-backend-developer-b-pune-0-to-3-years-271026000002", "Senior Backend Developer", "0-3 Yrs", "Just now", "B"),
            card("backend-developer-c-pune-3-to-5-years-271026000003", "Backend Developer", "3-5 Yrs", "Just now", "C"),
        )
        week = page(
            card("backend-developer-a-pune-0-to-3-years-271026000001", "Backend Developer", "0-3 Yrs", "Few Hours Ago", "A"),  # dup
            card("software-developer-d-pune-1-to-3-years-231026000004", "Software Developer", "1-3 Yrs", "4 Days Ago", "D"),
            card("software-developer-e-pune-1-to-3-years-201026000005", "Software Developer", "1-3 Yrs", "7 Days Ago", "E"),
            card("software-developer-f-pune-1-to-3-years-151026000006", "Software Developer", "1-3 Yrs", "12 Days Ago", "F"),
            card("backend-developer-g-pune-0-to-2-years-261026000007", "Backend Developer", "0-2 Yrs", "1 Day Ago", "G"),
        )
        return {1: fresh, 7: week}

    def test_newest_first_and_filtered(self):
        jobs = search.collect_candidates(FakeDriver(self.pages()), self.tracker, target_pool=50)
        self.assertEqual([j.company for j in jobs], ["A", "G", "D", "E"])
        self.assertEqual([j.tier for j in jobs], [0, 0, 1, 1])

    def test_previously_applied_job_not_returned(self):
        first = search.collect_candidates(FakeDriver(self.pages()), self.tracker, target_pool=50)
        self.tracker.record(first[0], "applied")                       # applied to A on "run 1"
        second = search.collect_candidates(FakeDriver(self.pages()), Tracker(Path(self.tmp.name) / "a.csv"), target_pool=50)
        self.assertNotIn("A", [j.company for j in second])

    def test_does_not_widen_to_7_days_when_enough_fresh_jobs(self):
        d = FakeDriver(self.pages())
        search.collect_candidates(d, self.tracker, target_pool=1)      # job A alone already satisfies a pool of 1
        self.assertTrue(all("jobAge=1" in u for u in d.urls), d.urls)

    def test_widens_to_7_days_when_not_enough(self):
        d = FakeDriver(self.pages())
        search.collect_candidates(d, self.tracker, target_pool=50)
        self.assertTrue(any("jobAge=1" in u for u in d.urls) and any("jobAge=7" in u for u in d.urls))
        self.assertLess([i for i, u in enumerate(d.urls) if "jobAge=1" in u][-1],
                        [i for i, u in enumerate(d.urls) if "jobAge=7" in u][0])


if __name__ == "__main__":
    unittest.main()
