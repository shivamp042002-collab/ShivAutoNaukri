"""Instant, offline answers for the questions Naukri asks most often - no API call, no waiting.

Everything here is derived from YOUR profile.json.  If a rule is not sure, it returns None and the question
goes to the cache / Gemini instead, so nothing is ever guessed silently.

profile.json fields used (all optional):
    total_experience_years, skill_experience_years, current_location, nationality,
    notice_period_days, current_ctc_lpa, expected_ctc_lpa,
    say_yes_to_willingness_questions   (default true: "willing to relocate / shifts / travel?" -> Yes)
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .utils import normalize


@dataclass
class Answer:
    text: str = ""
    indexes: Optional[List[int]] = None       # 1-based option numbers for choice questions
    source: str = "gemini"                    # gemini | cache | profile | rule


# ---------------------------------------------------------------- patterns
WILLING = re.compile(
    r"\b(willing|willingness|ready to|comfortable|open to|okay with|ok with|fine with|agree to|"
    r"can you (join|relocate|travel|work|commute)|able to (join|relocate|travel|work|commute)|"
    r"relocat\w*|rotational|night shifts?|shift timings?|work from (office|home)|wfo|wfh|commute|"
    r"travel to|interested|kindly apply|apply in (the|this) link|walk[- ]?in|available for)\b")
# never auto-say-yes to anything that smells like a trap or a cost to the candidate
RISKY = re.compile(
    r"(criminal|convict|arrest|disabilit|\bbond\b|unpaid|without (a )?(salary|pay)|salary (cut|reduc|less)|"
    r"reduced (salary|pay)|registration fee|training fee|deposit|pay (us|a fee|fee|fees)|security amount)")
APPLIED_BEFORE = re.compile(
    r"\b(applied|interviewed|appeared)\b.*\b(earlier|before|previously|in the past|ever)\b|"
    r"\b(earlier|previously|before)\b.*\b(applied|interviewed)\b")

GENERIC_TOKENS = {
    "total", "overall", "relevant", "work", "working", "professional", "your", "you", "do", "have", "how", "many",
    "much", "years", "year", "yrs", "yr", "of", "experience", "exp", "in", "what", "is", "the", "are", "please",
    "enter", "mention", "any", "a", "an", "and", "months", "month", "current", "total.", "field", "number", "no",
}


# ---------------------------------------------------------------- option helpers
def _real(options: Sequence[str]) -> List[Tuple[int, str]]:
    """(1-based index, normalized label) of options that are not 'Skip this question'."""
    return [(i, normalize(o)) for i, o in enumerate(options, 1) if not normalize(o).startswith("skip")]


def _yes_index(options: Sequence[str]) -> Optional[int]:
    for i, n in _real(options):
        if not n.startswith("not") and n.split(" ")[0] in {"yes", "y", "willing", "interested", "sure", "definitely", "ok", "okay"}:
            return i
    return None


def _no_index(options: Sequence[str]) -> Optional[int]:
    for i, n in _real(options):
        if n.split(" ")[0] in {"no", "not", "n", "never"}:
            return i
    return None


def _is_yes_no(options: Sequence[str]) -> bool:
    return bool(options) and _yes_index(options) is not None and _no_index(options) is not None


def _numeric_option(value: float, options: Sequence[str]) -> Optional[int]:
    """Pick the option whose range contains `value`: '0-1 years', '3+ years', 'Fresher', 'Less than 1 year'."""
    for i, n in _real(options):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", n)
        if m and float(m.group(1)) <= value <= float(m.group(2)):
            return i
        m = re.search(r"(\d+(?:\.\d+)?)\s*\+", n)
        if m and value >= float(m.group(1)):
            return i
        m = re.search(r"(?:less than|under|below|<)\s*(\d+(?:\.\d+)?)", n)
        if m and value < float(m.group(1)):
            return i
        if value == 0 and re.search(r"\b(fresher|no experience|none|nil)\b", n):
            return i
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*(?:years?|yrs?))?", n)
        if m and float(m.group(1)) == value:
            return i
    return None


def _num(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f.is_integer() else str(round(f, 1))


# ---------------------------------------------------------------- the rules
def _experience(q: str, options: Sequence[str], profile: dict) -> Optional[Answer]:
    tokens = re.findall(r"[a-z0-9.+#]+", q)
    if "experience" not in tokens and "exp" not in tokens:
        return None
    total = profile.get("total_experience_years")
    skills = {normalize(k): v for k, v in (profile.get("skill_experience_years") or {}).items()}
    remaining = [t for t in tokens if t not in GENERIC_TOKENS]

    value = None
    if not remaining:                                           # "Total experience (in years)"
        value = total
    else:                                                       # "... experience in Python"
        for key, years in skills.items():
            if key and all(t in tokens for t in re.findall(r"[a-z0-9.+#]+", key)):
                value = years
                break
    if value is None:
        return None

    if options:
        if _is_yes_no(options):                                 # "Do you have experience in Python?"
            idx = _yes_index(options) if float(value) > 0 else _no_index(options)
        else:
            idx = _numeric_option(float(value), options)
        return Answer(text=options[idx - 1], indexes=[idx], source="rule") if idx else None
    return Answer(text=_num(value), source="rule")


def quick_answer(question: str, options: Sequence[str], profile: dict, multi: bool = False) -> Optional[Answer]:
    """Return an Answer from simple rules + the profile, or None if unsure."""
    q = normalize(question)
    q = re.sub(r"^\s*\d+[.)]\s*", "", q)                          # strip "1. " numbering
    if not q or multi:
        return None
    profile = profile or {}
    options = list(options or [])

    # 1) "Have you applied to X earlier?"  -> No   (we only apply once per job; a repeat applicant is never us)
    if APPLIED_BEFORE.search(q):
        idx = _no_index(options)
        if idx:
            return Answer(text=options[idx - 1], indexes=[idx], source="rule")
        if not options:
            return Answer(text="No", source="rule")
        return None

    # 2) willingness / interest -> Yes (switch off with "say_yes_to_willingness_questions": false)
    if (profile.get("say_yes_to_willingness_questions", True) and WILLING.search(q) and not RISKY.search(q)):
        if options:
            idx = _yes_index(options)
            if idx:
                return Answer(text=options[idx - 1], indexes=[idx], source="rule")
        else:
            return Answer(text="Yes", source="rule")

    # 3) years of experience (total / relevant / per skill)
    ans = _experience(q, options, profile)
    if ans:
        return ans

    # 4) nationality
    if re.search(r"\b(nationality|citizenship)\b", q):
        nat = normalize(profile.get("nationality", "Indian"))
        if options:
            for i, n in _real(options):
                if nat and nat in n:
                    return Answer(text=options[i - 1], indexes=[i], source="rule")
            return None
        return Answer(text=profile.get("nationality", "Indian"), source="rule")

    # 5) free-text facts
    if not options:
        if re.search(r"\b(current|present)\s+(location|city)\b|where are you (currently )?(located|based|living)", q):
            loc = profile.get("current_location")
            if loc:
                return Answer(text=str(loc), source="rule")
        if re.search(r"\bexpected\s+(ctc|salary|compensation)\b", q) and profile.get("expected_ctc_lpa") is not None:
            return Answer(text=_num(profile["expected_ctc_lpa"]), source="rule")
        if re.search(r"\bcurrent\s+(ctc|salary|compensation)\b", q) and profile.get("current_ctc_lpa") is not None:
            return Answer(text=_num(profile["current_ctc_lpa"]), source="rule")
        if re.search(r"\bnotice period\b", q) and profile.get("notice_period_days") is not None:
            return Answer(text=_num(profile["notice_period_days"]), source="rule")
    return None