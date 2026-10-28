import tempfile
import unittest
from pathlib import Path

from jobsailor.gemini_client import (GeminiAnswerer, find_override,
                                     match_option_by_text, parse_indexes)

PROFILE = {"name": "X", "total_experience_years": 2,
           "answers": {"notice period": "30", "relocate": "Yes", "expected ctc": "9"}}


class Fake(GeminiAnswerer):
    """Replaces the network call with canned replies."""
    def __init__(self, replies, *a, **k):
        super().__init__("key", PROFILE, *a, **k)
        self.replies = list(replies)
        self.prompts = []

    def _generate(self, model, prompt):
        self.prompts.append((model, prompt))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class ParseTests(unittest.TestCase):
    def test_parse_indexes(self):
        self.assertEqual(parse_indexes("2", 4), [2])
        self.assertEqual(parse_indexes("Option 3.", 4), [3])
        self.assertEqual(parse_indexes("9", 4), [])                 # out of range
        self.assertEqual(parse_indexes("1, 3, 3", 4, multi=True), [1, 3])
        self.assertEqual(parse_indexes("1, 3", 4, multi=False), [1])

    def test_match_option_by_text(self):
        self.assertEqual(match_option_by_text("Yes", ["Yes", "No"]), 1)
        self.assertEqual(match_option_by_text("30", ["15 days", "30 days", "60 days"]), 2)
        self.assertIsNone(match_option_by_text("maybe", ["Yes", "No"]))

    def test_override_longest_keyword_wins(self):
        ov = {"ctc": "1", "expected ctc": "9"}
        self.assertEqual(find_override("What is your Expected CTC?", ov), "9")
        self.assertIsNone(find_override("Favourite colour?", ov))


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.kw = dict(cache_path=Path(self.d.name) / "c.json", qa_log_path=Path(self.d.name) / "qa.csv",
                       fallback_models=["fallback-model"])

    def tearDown(self):
        self.d.cleanup()

    def test_profile_override_needs_no_api_call(self):
        g = Fake([], **self.kw)
        a = g.answer("What is your notice period (in days)?")
        self.assertEqual((a.text, a.source), ("30", "profile"))
        a = g.answer("Are you willing to relocate?", ["Yes", "No"])
        self.assertEqual((a.indexes, a.source), ([1], "profile"))
        self.assertEqual(g.prompts, [])

    def test_choice_answer_and_cache(self):
        g = Fake(["2"], **self.kw)
        opts = ["Python", "Java", "Go"]
        a = g.answer("Which language do you use most?", opts)
        self.assertEqual(a.indexes, [2])
        b = g.answer("Which language do you use most?", opts)       # second time -> cache, no more replies left
        self.assertEqual((b.indexes, b.source), ([2], "cache"))
        self.assertEqual(len(g.prompts), 1)
        # cache survives a restart
        g2 = Fake([], **self.kw)
        self.assertEqual(g2.answer("Which language do you use most?", opts).indexes, [2])

    def test_model_answers_with_text_instead_of_number(self):
        g = Fake(["Java"], **self.kw)
        self.assertEqual(g.answer("Pick one", ["Python", "Java"]).indexes, [2])

    def test_unmappable_reply_returns_none_instead_of_guessing(self):
        g = Fake(["I am not sure"], **self.kw)
        self.assertIsNone(g.answer("Pick one", ["Python", "Java"]))

    def test_text_answer_single_line(self):
        g = Fake(['"3"\nBecause...'], **self.kw)
        self.assertEqual(g.answer("How many years of Django experience do you have?").text, "3")

    def test_fallback_model_used_when_first_not_found(self):
        g = Fake([RuntimeError("404 models/x is not found"), "2"], **self.kw)
        a = g.answer("Pick", ["A", "B"])
        self.assertEqual(a.indexes, [2])
        self.assertEqual([m for m, _ in g.prompts], ["gemini-flash-latest", "fallback-model"])

    def test_bad_api_key_returns_none(self):
        g = Fake([RuntimeError("403 API key not valid")], **self.kw)
        self.assertIsNone(g.answer("Pick", ["A", "B"]))

    def test_qa_log_written(self):
        g = Fake(["1"], **self.kw)
        g.answer("Pick", ["A", "B"])
        self.assertIn("Pick", (Path(self.d.name) / "qa.csv").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
