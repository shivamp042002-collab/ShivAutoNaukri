"""Firefox start-up and Naukri login handling."""
import logging
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

import config

log = logging.getLogger("jobsailor")


def make_driver(headless: bool = None):
    """Start Firefox with a persistent profile (so your Naukri login is remembered)."""
    options = Options()
    if config.FIREFOX_BINARY:
        options.binary_location = config.FIREFOX_BINARY
    if config.HEADLESS if headless is None else headless:
        options.add_argument("-headless")
    options.page_load_strategy = "eager"      # don't wait for every ad/tracker image - much faster page loads
    options.add_argument("-width=1400")
    options.add_argument("-height=1000")

    config.FIREFOX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    options.add_argument("-profile")
    options.add_argument(str(config.FIREFOX_PROFILE_DIR))

    # Looks less like an automation script to the site.
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)

    service = Service(executable_path=config.GECKODRIVER_PATH) if config.GECKODRIVER_PATH else Service()
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    return driver


def safe_get(driver, url: str) -> None:
    """driver.get() that survives a slow page: on timeout, stop loading and carry on with what has rendered."""
    try:
        driver.get(url)
    except TimeoutException:
        log.warning("Slow page (%s) - continuing with what has loaded", url[:70])
        try:
            driver.execute_script("window.stop();")
        except Exception:  # noqa: BLE001
            pass


def _is_logged_in(driver) -> bool:
    url = driver.current_url.lower()
    if "nlogin" in url or "login" in url.split("naukri.com")[-1][:20]:
        return False
    if driver.find_elements(By.ID, "login_Layer"):
        return False
    # Logged-in pages show the profile menu / drawer
    markers = [
        "//*[contains(@class,'nI-gNb-drawer__icon')]",
        "//a[contains(@href,'/mnjuser/profile')]",
        "//*[contains(@class,'nI-gNb-bar2')]",
    ]
    return any(driver.find_elements(By.XPATH, m) for m in markers)


def ensure_logged_in(driver, interactive: bool = True) -> bool:
    """Open Naukri; if not logged in, let the human log in once (profile remembers it)."""
    safe_get(driver, "https://www.naukri.com/mnjuser/homepage")
    time.sleep(4)
    if _is_logged_in(driver):
        log.info("Naukri: already logged in.")
        return True
    if not interactive:
        log.error("Not logged in to Naukri and running non-interactively.")
        return False

    print("\n" + "=" * 60)
    print(" Please LOG IN to Naukri in the Firefox window that just opened.")
    print(" (Only needed once - the login is remembered in data/firefox_profile)")
    print(" When you see your Naukri home page, come back here and press Enter.")
    print("=" * 60)
    safe_get(driver, "https://www.naukri.com/nlogin/login")
    input("Press Enter after logging in... ")
    safe_get(driver, "https://www.naukri.com/mnjuser/homepage")
    time.sleep(3)
    ok = _is_logged_in(driver)
    log.info("Naukri login %s.", "confirmed" if ok else "NOT detected")
    return ok


def looks_blocked(driver) -> bool:
    """True only for a real captcha / 'access denied' page (checks title + visible text, not raw HTML,
    because normal Naukri pages always contain the word 'captcha' in their scripts)."""
    try:
        title = (driver.title or "").lower()
        body = driver.find_element(By.TAG_NAME, "body").text.lower()[:3000]
    except Exception:  # noqa: BLE001
        return False
    if any(s in title for s in ("access denied", "just a moment", "captcha", "blocked")):
        return True
    return any(s in body for s in ("access denied", "are you a robot", "verify you are human",
                                   "unusual traffic", "complete the captcha"))