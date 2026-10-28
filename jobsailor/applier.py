"""Opens one Naukri job, clicks Apply and answers the chatbot questions with Gemini."""
import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional

from bs4 import BeautifulSoup
from selenium.common.exceptions import (StaleElementReferenceException, TimeoutException,
                                        WebDriverException)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config
from .filters import description_match_score

log = logging.getLogger("jobsailor")

# ------------------------------------------------------------------ outcomes
APPLIED = "applied"
ALREADY = "already_applied"
EXTERNAL = "external_site"
EXPIRED = "expired"
LOW_MATCH = "low_match"
FAILED = "failed"

# ------------------------------------------------------------------ selectors (edit here if Naukri changes its HTML)
SUCCESS_XPATHS = [
    "//span[contains(@class,'apply-message') and contains(.,'successfully applied')]",
    "//*[contains(@class,'apply-status-header') and contains(@class,'green')]",
    "//*[contains(text(),'You have successfully applied')]",
]
ALREADY_APPLIED_XPATHS = [
    "//*[@id='already-applied']",
    "//*[contains(text(),'You have already applied')]",
]
EXPIRED_XPATHS = [
    "//*[contains(@class,'styles_alert-message-text')]",
    "//*[contains(text(),'job has expired') or contains(text(),'no longer accepting') or contains(text(),'Job you are looking for is no longer')]",
]
EXTERNAL_XPATHS = [
    "//*[@id='company-site-button']",
    "//button[contains(.,'Apply on company site')]",
]
APPLY_BUTTON_XPATHS = [
    "//button[@id='apply-button']",
    "//button[normalize-space()='Apply']",
    "//*[normalize-space(text())='Apply']",
]
QUESTION_XPATHS = [
    "(//li[contains(@class,'botItem')])[last()]",
    "(//div[contains(@class,'botMsg')])[last()]",
]
RADIO_CSS = ".ssrc__radio-btn-container"
CHECKBOX_CSS = ".mcc__checkbox-container, .multiselect-container .checkbox-container"
CHIP_CSS = ".chatbot_Chip, .chipsContainer .chip"
TEXT_INPUT_XPATHS = [
    "//div[contains(@class,'textArea') and @contenteditable='true']",
    "//div[@class='textArea']",
    "//div[@contenteditable='true']",
    "//input[contains(@class,'chatbot') and @type='text']",
]
SAVE_BUTTON_XPATHS = [
    "//div[contains(@class,'sendMsg')]",
    "//div[contains(@class,'send') and normalize-space()='Save']",
    "//button[normalize-space()='Save']",
    "//*[normalize-space(text())='Save']",
    "/html/body/div[2]/div/div[1]/div[3]/div/div",          # the original script's absolute path (last resort)
]
JD_CSS = [".styles_JDC__dang-inner-html__h0K4t", ".job-desc", "[class*='job-desc']", "[class*='dang-inner-html']"]


@dataclass
class ApplyResult:
    status: str
    detail: str = ""
    questions: int = 0


# ------------------------------------------------------------------ tiny DOM helpers
def _find_any(driver, xpaths: List[str]):
    for xp in xpaths:
        try:
            els = driver.find_elements(By.XPATH, xp)
        except WebDriverException:
            continue
        els = [e for e in els if _safe_displayed(e)]
        if els:
            return els[0]
    return None


def _safe_displayed(el) -> bool:
    try:
        return el.is_displayed()
    except WebDriverException:
        return False


def _js_click(driver, el) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        el.click()
    except WebDriverException:
        driver.execute_script("arguments[0].click();", el)


def _success_visible(driver) -> bool:
    return any(driver.find_elements(By.XPATH, xp) for xp in SUCCESS_XPATHS)


def _wait_success(driver, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if _success_visible(driver):
            return True
        time.sleep(0.4)
    return False


def _job_description(driver) -> str:
    try:
        soup = BeautifulSoup(driver.page_source, "html.parser")
    except WebDriverException:
        return ""
    parts = []
    for sel in JD_CSS:
        for el in soup.select(sel):
            t = el.get_text(" ", strip=True)
            if len(t) > 80:
                parts.append(t)
    return " ".join(parts)


# ------------------------------------------------------------------ chatbot questions
def _click_save(driver) -> bool:
    for xp in SAVE_BUTTON_XPATHS:
        try:
            WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.XPATH, xp)))
            el = driver.find_element(By.XPATH, xp)
            _js_click(driver, el)
            return True
        except (TimeoutException, WebDriverException):
            continue
    return False


def _current_question(driver) -> str:
    for xp in QUESTION_XPATHS:
        els = driver.find_elements(By.XPATH, xp)
        if els:
            txt = els[-1].text.strip()
            if txt:
                return txt
    return ""


def _option_label(el) -> str:
    try:
        lab = el.find_element(By.CSS_SELECTOR, "label")
        if lab.text.strip():
            return lab.text.strip()
    except WebDriverException:
        pass
    return (el.text or "").strip()


def _choice_widgets(driver):
    """(radios, checkboxes, chips) currently visible."""
    vis = lambda css: [e for e in driver.find_elements(By.CSS_SELECTOR, css) if _safe_displayed(e)]
    return vis(RADIO_CSS), vis(CHECKBOX_CSS), vis(CHIP_CSS)


def _answer_one_question(driver, answerer) -> Optional[bool]:
    """Handle whatever question is currently on screen.
    Returns True = answered, False = could not answer, None = no question UI visible yet."""
    question = _current_question(driver)
    groups = _choice_widgets(driver)
    text_input = _find_any(driver, TEXT_INPUT_XPATHS)

    # ---- choice questions (radio / multi-select / chips)
    for g, (multi, needs_save) in enumerate(((False, True), (True, True), (False, False))):
        widgets = groups[g]
        if not widgets:
            continue
        labels = [_option_label(w) for w in widgets]
        log.info("   Q: %s  %s", question, labels)
        ans = answerer.answer(question, labels, multi=multi)      # may take a few seconds
        if not ans or not ans.indexes:
            return False
        fresh = _choice_widgets(driver)[g]                        # the page may have re-rendered meanwhile
        if len(fresh) == len(widgets):
            widgets = fresh
        for idx in ans.indexes:
            target = widgets[idx - 1]
            try:
                inp = target.find_element(By.CSS_SELECTOR, "input")
            except WebDriverException:
                inp = target
            driver.execute_script("arguments[0].click();", inp)
        log.info("   A: %s  (%s)", ans.text, ans.source)
        if needs_save:
            time.sleep(0.4)
            _click_save(driver)
        return True

    # ---- free-text questions
    if text_input is not None and question:
        log.info("   Q: %s", question)
        ans = answerer.answer(question)
        if not ans or not ans.text:
            return False
        text_input = _find_any(driver, TEXT_INPUT_XPATHS) or text_input   # re-find after the wait
        try:
            text_input.click()
        except WebDriverException:
            pass
        text_input.send_keys(ans.text)
        log.info("   A: %s  (%s)", ans.text, ans.source)
        time.sleep(0.5)
        if not _click_save(driver):
            from selenium.webdriver.common.keys import Keys
            text_input.send_keys(Keys.ENTER)
        return True

    return None


def _answer_questions(driver, answerer) -> ApplyResult:
    answered = 0
    seen = Counter()
    idle = 0
    stale = 0
    for _ in range(config.MAX_QUESTIONS_PER_JOB * 3):
        if _success_visible(driver):
            return ApplyResult(APPLIED, "", answered)
        question = _current_question(driver)
        try:
            outcome = _answer_one_question(driver, answerer)
        except StaleElementReferenceException:     # page re-rendered under us - just look again
            stale += 1
            if stale > 4:
                return ApplyResult(FAILED, "page kept changing (stale element)", answered)
            time.sleep(0.8)
            continue
        if outcome is None:                       # nothing to answer yet
            idle += 1
            if idle >= 8:
                return ApplyResult(FAILED, "no success message and no recognisable question", answered)
            time.sleep(0.8)
            continue
        idle = 0
        if outcome is False:
            return ApplyResult(FAILED, f"could not answer: {question[:90]}", answered)
        answered += 1
        seen[question] += 1
        if seen[question] >= 3:
            return ApplyResult(FAILED, f"question keeps repeating: {question[:90]}", answered)
        if answered > config.MAX_QUESTIONS_PER_JOB:
            return ApplyResult(FAILED, "too many questions", answered)
        if _wait_success(driver, 1.5):
            return ApplyResult(APPLIED, "", answered)
    return ApplyResult(FAILED, "gave up answering questions", answered)


def _verify_applied(driver, url: str) -> bool:
    """After a failure, re-open the job: if Naukri now shows 'already applied', the application DID go through."""
    try:
        driver.get(url)
    except TimeoutException:
        pass
    except WebDriverException:
        return False
    time.sleep(2.5)
    try:
        return _find_any(driver, ALREADY_APPLIED_XPATHS) is not None
    except WebDriverException:
        return False


# ------------------------------------------------------------------ main entry
def apply_to_job(driver, job, answerer, dry_run: bool = False) -> ApplyResult:
    """Open the job page and try to apply. Never raises - always returns an ApplyResult."""
    state = {"clicked": False}
    result = _apply_flow(driver, job, answerer, dry_run, state)
    if result.status == FAILED and state["clicked"]:
        # A "failure" after clicking Apply may still have succeeded (success banner missed / page re-rendered).
        if _verify_applied(driver, job.url):
            return ApplyResult(APPLIED, f"confirmed on re-check (was: {result.detail[:60]})", result.questions)
    return result


def _apply_flow(driver, job, answerer, dry_run: bool, state: dict) -> ApplyResult:
    try:
        driver.get(job.url)
    except TimeoutException:
        pass                                      # page partly loaded is usually fine
    except WebDriverException as exc:
        return ApplyResult(FAILED, f"page load error: {str(exc)[:80]}")
    time.sleep(2.5)

    try:
        if _find_any(driver, ALREADY_APPLIED_XPATHS):
            return ApplyResult(ALREADY, "already applied on Naukri")
        if _find_any(driver, EXPIRED_XPATHS):
            return ApplyResult(EXPIRED, "job expired / not available")
        if _find_any(driver, EXTERNAL_XPATHS) and not _find_any(driver, ["//button[@id='apply-button']"]):
            return ApplyResult(EXTERNAL, "applies on the company website")

        if config.MIN_MATCH_SCORE:
            skills = answerer.profile.get("skills", []) if answerer else []
            job.match_score = description_match_score(_job_description(driver), skills)
            if job.match_score < config.MIN_MATCH_SCORE:
                return ApplyResult(LOW_MATCH, f"skill match {job.match_score}% < {config.MIN_MATCH_SCORE}%")

        button = _find_any(driver, APPLY_BUTTON_XPATHS)
        if button is None:
            return ApplyResult(FAILED, "Apply button not found")
        if dry_run:
            return ApplyResult("dry_run", "would apply")

        handles_before = set(driver.window_handles)
        state["clicked"] = True
        _js_click(driver, button)

        # quick success (no questions) ...
        if _wait_success(driver, 4):
            return ApplyResult(APPLIED, "", 0)
        # ... apply opened the company website in a new tab
        new_tabs = set(driver.window_handles) - handles_before
        if new_tabs:
            for h in new_tabs:
                driver.switch_to.window(h)
                driver.close()
            driver.switch_to.window(next(iter(handles_before)))
            return ApplyResult(EXTERNAL, "redirected to company website")

        return _answer_questions(driver, answerer)

    except Exception as exc:  # noqa: BLE001 - one bad job must never stop the run
        return ApplyResult(FAILED, f"{type(exc).__name__}: {str(exc)[:100]}")