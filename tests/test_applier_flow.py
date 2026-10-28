"""Drives apply_to_job() against a scripted fake browser that behaves like Naukri's apply chatbot.
It checks OUR control flow (click, answer, save, detect success, give up) - not Naukri's real HTML."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _selenium_stub
_selenium_stub.install()

from selenium.common.exceptions import NoSuchElementException  # noqa: E402

from jobsailor import applier  # noqa: E402
from jobsailor.filters import Job, evaluate  # noqa: E402
from jobsailor.gemini_client import GeminiAnswerer  # noqa: E402


class El:
    def __init__(self, text="", on_click=None, children=None, value=""):
        self.text, self.on_click, self.children, self.value, self.sent = text, on_click, children or {}, value, []
    def is_displayed(self): return True
    def click(self):
        if self.on_click: self.on_click()
    def send_keys(self, s): self.sent.append(s)
    def find_element(self, by, sel):
        if sel in self.children: return self.children[sel]
        raise NoSuchElementException()
    def get_attribute(self, n): return self.value


class FakeNaukri:
    """state: job -> q_radio -> q_text -> success   (or a variant given by `script`)"""
    def __init__(self, script=("radio", "text"), page="job"):
        self.state, self.page, self.script, self.step = "job", page, list(script), 0
        self.window_handles = ["main"]
        self.relocate_choice = None
        self.text_sent = None
        self.page_source = "<html></html>"
        self.visited = []

    # --- helpers that advance the chat
    def _next(self):
        if self.step >= len(self.script): self.state = "success"
        else: self.state, self.step = self.script[self.step], self.step + 1
    def _pick(self, label): self.relocate_choice = label

    # --- selenium API
    def get(self, url): self.visited.append(url)
    def switch_to(self): ...
    def execute_script(self, script, *args):
        if "click()" in script and args: args[0].click()
    def find_element(self, by, sel):
        r = self.find_elements(by, sel)
        if not r: raise NoSuchElementException()
        return r[0]
    def find_elements(self, by, sel):
        s, p = self.state, self.page
        if p == "already" and "already-applied" in sel: return [El()]
        if p == "expired" and "alert-message-text" in sel: return [El("expired")]
        if p == "external" and "company-site-button" in sel: return [El()]
        if s == "job" and p == "job" and "apply-button" in sel and "button" in sel: return [El("Apply", self._next)]
        if s in ("radio", "text") and "botItem" in sel:
            return [El("Are you willing to relocate?" if s == "radio" else "What is your expected CTC?")]
        if s == "radio" and sel == applier.RADIO_CSS:
            return [El(children={"label": El("Yes"), "input": El(on_click=lambda: self._pick("Yes"))}),
                    El(children={"label": El("No"), "input": El(on_click=lambda: self._pick("No"))})]
        if s == "text" and "textArea" in sel and "contenteditable" in sel:
            self.text_el = getattr(self, "text_el", None) or El()
            return [self.text_el]
        if s in ("radio", "text") and "sendMsg" in sel: return [El("Save", self._next)]
        if s == "success" and "apply-message" in sel: return [El("You have successfully applied")]
        return []


class StubAnswerer:
    profile = {"skills": ["python"]}
    def __init__(self, fail=False): self.asked, self.fail = [], fail
    def answer(self, q, options=(), multi=False):
        self.asked.append(q)
        if self.fail: return None
        if options: return type("A", (), {"indexes": [1], "text": options[0], "source": "stub"})()
        return type("A", (), {"indexes": None, "text": "9", "source": "stub"})()


def job():
    return evaluate(Job(url="https://www.naukri.com/job-listings-backend-developer-acme-pune-0-to-3-years-271026000001",
                        title="Backend Developer", experience_text="0-3 Yrs", posted_text="Just now"))


class ApplierFlowTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(applier.time, "sleep", lambda *_: None)
        p.start(); self.addCleanup(p.stop)

    def run_flow(self, driver, answerer=None):
        answerer = answerer or StubAnswerer()
        return applier.apply_to_job(driver, job(), answerer), answerer

    def test_no_question_job(self):
        d = FakeNaukri(script=())
        res, _ = self.run_flow(d)
        self.assertEqual((res.status, res.questions), ("applied", 0))

    def test_radio_then_text_question(self):
        d = FakeNaukri(script=("radio", "text"))
        res, a = self.run_flow(d)
        self.assertEqual(res.status, "applied", res.detail)
        self.assertEqual(res.questions, 2)
        self.assertEqual(d.relocate_choice, "Yes")
        self.assertEqual(d.text_el.sent, ["9"])
        self.assertEqual(a.asked, ["Are you willing to relocate?", "What is your expected CTC?"])

    def test_unanswerable_question_fails_cleanly(self):
        res, _ = self.run_flow(FakeNaukri(script=("radio",)), StubAnswerer(fail=True))
        self.assertEqual(res.status, "failed")
        self.assertIn("could not answer", res.detail)

    def test_already_applied_expired_external(self):
        for page, status in (("already", "already_applied"), ("expired", "expired"), ("external", "external_site")):
            res, _ = self.run_flow(FakeNaukri(page=page))
            self.assertEqual(res.status, status, page)

    def test_dry_run_does_not_click_apply(self):
        d = FakeNaukri()
        res = applier.apply_to_job(d, job(), StubAnswerer(), dry_run=True)
        self.assertEqual(res.status, "dry_run")
        self.assertEqual(d.state, "job")

    def test_missing_apply_button(self):
        d = FakeNaukri(); d.state = "nothing"
        res, _ = self.run_flow(d)
        self.assertEqual(res.status, "failed")


if __name__ == "__main__":
    unittest.main()
