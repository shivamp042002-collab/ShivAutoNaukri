"""Installs a tiny fake `selenium` ONLY when the real one is not installed (lets the flow tests run anywhere)."""
import sys
import types


def install():
    try:
        import selenium  # noqa: F401
        return
    except ImportError:
        pass

    def mod(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    sel = mod("selenium")
    exc = mod("selenium.common.exceptions")
    mod("selenium.common")
    class WebDriverException(Exception): ...
    class TimeoutException(WebDriverException): ...
    class NoSuchElementException(WebDriverException): ...
    exc.WebDriverException, exc.TimeoutException, exc.NoSuchElementException = (
        WebDriverException, TimeoutException, NoSuchElementException)

    wd = mod("selenium.webdriver")
    mod("selenium.webdriver.common")
    by = mod("selenium.webdriver.common.by")
    class By:
        XPATH = "xpath"; CSS_SELECTOR = "css"; ID = "id"; TAG_NAME = "tag name"; CLASS_NAME = "class name"
    by.By = By
    keys = mod("selenium.webdriver.common.keys")
    class Keys:
        ENTER = ""
    keys.Keys = Keys

    mod("selenium.webdriver.support")
    ec = mod("selenium.webdriver.support.expected_conditions")
    ec.presence_of_element_located = lambda loc: (lambda d: d.find_element(*loc))
    ui = mod("selenium.webdriver.support.ui")
    class WebDriverWait:
        def __init__(self, driver, timeout): self.d = driver
        def until(self, cond):
            try:
                r = cond(self.d)
            except NoSuchElementException:
                r = None
            if not r:
                raise TimeoutException()
            return r
    ui.WebDriverWait = WebDriverWait
    sup = sys.modules["selenium.webdriver.support"]
    sup.expected_conditions, sup.ui = ec, ui
    wd.common = sys.modules["selenium.webdriver.common"]
    sel.common = sys.modules["selenium.common"]
    sel.webdriver = wd
