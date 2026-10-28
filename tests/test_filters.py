import unittest
from datetime import date

from jobsailor import filters
from jobsailor.filters import Job, evaluate, prioritise
from jobsailor.utils import (age_days_from_text, job_id_from_url, job_key,
                             parse_experience, posted_date_from_id)

TODAY = date(2026, 10, 27)


def mk(slug, title="Backend Developer", exp="", posted="", company="Acme"):
    return Job(url=f"https://www.naukri.com/job-listings-{slug}", title=title,
               experience_text=exp, posted_text=posted, company=company)


class UtilsTests(unittest.TestCase):
    def test_job_id_and_date(self):
        url = "https://www.naukri.com/job-listings-backend-developer-x-pune-0-to-2-years-261026028027?src=a"
        self.assertEqual(job_id_from_url(url), "261026028027")
        self.assertEqual(posted_date_from_id("261026028027"), date(2026, 10, 26))
        self.assertIsNone(posted_date_from_id("999999028027"))     # invalid date
        self.assertIsNone(job_id_from_url("https://www.naukri.com/python-developer-jobs"))

    def test_key_ignores_query_and_company_slug(self):
        a = "https://www.naukri.com/job-listings-a-b-1-to-3-years-261026028027?src=x"
        b = "https://www.naukri.com/job-listings-a-b-1-to-3-years-261026028027"
        self.assertEqual(job_key(a), job_key(b))

    def test_parse_experience(self):
        self.assertEqual(parse_experience("0-3 Yrs"), (0, 3))
        self.assertEqual(parse_experience("1 to 3 years"), (1, 3))
        self.assertEqual(parse_experience("", "x-pune-1-to-3-years-261026028027"), (1, 3))
        self.assertEqual(parse_experience("Fresher"), (0, 0))
        self.assertEqual(parse_experience("5+ Yrs")[1], 99)
        self.assertIsNone(parse_experience("no info"))

    def test_age_text(self):
        self.assertEqual(age_days_from_text("Just now"), 0)
        self.assertEqual(age_days_from_text("Few Hours Ago"), 0)
        self.assertEqual(age_days_from_text("1 Day Ago"), 1)
        self.assertEqual(age_days_from_text("5 Days Ago"), 5)
        self.assertEqual(age_days_from_text("30+ Days Ago"), 30)
        self.assertIsNone(age_days_from_text(""))


class ExperienceRuleTests(unittest.TestCase):
    def check(self, exp_text):
        return evaluate(mk("x-pune-%s-261026028027" % exp_text.replace(" ", "-").lower(), exp=exp_text,
                           posted="Just now"), TODAY).reject_reason

    def test_allowed_ranges(self):
        for e in ("0-1 Yrs", "0-2 Yrs", "0-3 Yrs", "1-2 Yrs", "1-3 Yrs", "Fresher"):
            self.assertEqual(self.check(e), "", e)

    def test_rejected_ranges(self):
        for e in ("2-4 Yrs", "3-5 Yrs", "1-4 Yrs", "0-5 Yrs", "5+ Yrs", "2-3 Yrs"):
            self.assertNotEqual(self.check(e), "", e)

    def test_missing_experience_rejected(self):
        j = evaluate(Job(url="https://www.naukri.com/job-listings-backend-developer-acme-261026028027",
                         title="Backend Developer", posted_text="Just now"), TODAY)
        self.assertIn("experience", j.reject_reason)


class RecencyTests(unittest.TestCase):
    def test_tiers_from_card_text(self):
        self.assertEqual(evaluate(mk("a-0-to-3-years-261026000001", exp="0-3 Yrs", posted="Few Hours Ago"), TODAY).tier, 0)
        self.assertEqual(evaluate(mk("a-0-to-3-years-261026000001", exp="0-3 Yrs", posted="1 Day Ago"), TODAY).tier, 0)
        self.assertEqual(evaluate(mk("a-0-to-3-years-261026000001", exp="0-3 Yrs", posted="4 Days Ago"), TODAY).tier, 1)
        self.assertNotEqual(evaluate(mk("a-0-to-3-years-261026000001", exp="0-3 Yrs", posted="8 Days Ago"), TODAY).reject_reason, "")

    def test_tiers_from_job_id_when_no_card_text(self):
        today_job = evaluate(mk("a-0-to-3-years-271026000001", exp="0-3 Yrs"), TODAY)
        week_job = evaluate(mk("a-0-to-3-years-221026000001", exp="0-3 Yrs"), TODAY)
        old_job = evaluate(mk("a-0-to-3-years-100226000001", exp="0-3 Yrs"), TODAY)
        self.assertEqual((today_job.tier, week_job.tier), (0, 1))
        self.assertIn("too old", old_job.reject_reason)

    def test_priority_order_newest_first(self):
        jobs = [evaluate(mk(f"j{i}-0-to-3-years-26102600000{i}", exp="0-3 Yrs", posted=p), TODAY)
                for i, p in enumerate(["5 Days Ago", "Just now", "3 Days Ago", "1 Day Ago", "6 Days Ago"])]
        order = [j.age_days for j in prioritise(jobs)]
        self.assertEqual(order, sorted(order))
        self.assertEqual([j.tier for j in prioritise(jobs)], [0, 0, 1, 1, 1])


class TitleRuleTests(unittest.TestCase):
    def ok(self, title):
        return evaluate(mk("t-0-to-3-years-271026000001", title=title, exp="0-3 Yrs", posted="Just now"), TODAY).reject_reason == ""

    def test_titles(self):
        for t in ("Python Backend Developer", "Software Engineer", "Java Developer", "SDE-1", "Node.js Developer"):
            self.assertTrue(self.ok(t), t)
        for t in ("Senior Software Engineer", "Tech Lead - Python", "QA Engineer", "Sales Executive", "Engineering Manager"):
            self.assertFalse(self.ok(t), t)

    def test_short_token_is_whole_word(self):
        self.assertTrue(self.ok("Software Developer Squad"))      # 'qa' must not match inside 'squad'


class MatchScoreTests(unittest.TestCase):
    def test_score(self):
        self.assertEqual(filters.description_match_score("We use Python and Django on AWS", ["Python", "Django", "Java", "AWS"]), 75)
        self.assertEqual(filters.description_match_score("x", []), 100)


if __name__ == "__main__":
    unittest.main()
