"""Answers Naukri's application questions with Gemini, using your profile.json as the source of truth."""
import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

import config
from .utils import normalize

log = logging.getLogger("jobsailor")

SYSTEM_PROMPT = """You are filling in a job application on behalf of the candidate described in the PROFILE below.
Answer exactly as that candidate would, using only facts from the profile.

Rules:
- Multiple-choice question (options are numbered): reply with ONLY the option number. If several options may be
  selected (multi-select), reply with the numbers separated by commas, e.g. "1,3". Nothing else.
- Yes/No question without numbered options: reply "Yes" or "No".
- Numeric question (years of experience, CTC / salary, notice period, number of offers, etc.): reply with digits only,
  no units, no words. CTC/salary is in LAKHS PER ANNUM unless the question says otherwise. Notice period is in DAYS.
- "Years of experience in <skill>": use the number in the profile's skill_experience_years if present. If the skill is
  related to the profile, give a conservative value that is never higher than total_experience_years. If the skill is
  clearly unrelated, reply 0.
- Text question: one short line (max 12 words); for open-ended "why / tell us about" questions at most 2 short sentences.
- If the profile has no information, give the most neutral, honest and conservative answer. Never invent employers,
  degrees, certificates or numbers that contradict the profile.
- NEVER choose an option such as "Skip this question", "Skip", or "Prefer not to say" when a real answer exists.
- Never explain, never add quotes, markdown or labels.

PROFILE (JSON):
"""


@dataclass
class Answer:
    text: str = ""
    indexes: Optional[List[int]] = None       # 1-based option numbers for choice questions
    source: str = "gemini"                    # gemini | cache | profile


# ---------------------------------------------------------------- pure helpers (unit-tested)

def parse_indexes(reply: str, n_options: int, multi: bool = False) -> List[int]:
    """Pull valid 1-based option numbers out of a model reply."""
    nums = [int(x) for x in re.findall(r"\d+", reply or "")]
    nums = [n for n in nums if 1 <= n <= n_options]
    seen, out = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n)
            out.append(n)
    if not multi:
        return out[:1]
    return out


def match_option_by_text(answer: str, options: Sequence[str]) -> Optional[int]:
    """Return the 1-based index of the option that best matches a free-text answer (used for profile overrides)."""
    a = normalize(answer)
    if not a:
        return None
    for i, opt in enumerate(options, 1):        # exact
        if normalize(opt) == a:
            return i
    for i, opt in enumerate(options, 1):        # containment either way
        o = normalize(opt)
        if o and (a in o or o in a):
            return i
    return None


def find_override(question: str, overrides: dict) -> Optional[str]:
    """profile.json -> "answers": {"notice period": "15", ...}.  Longest matching keyword wins."""
    q = normalize(question)
    best = None
    for key, val in (overrides or {}).items():
        k = normalize(key)
        if k and k in q and (best is None or len(k) > len(best[0])):
            best = (k, str(val))
    return best[1] if best else None


class GeminiAnswerer:
    def __init__(self, api_key: str, profile: dict, model: str = None, fallback_models=None,
                 cache_path: Path = None, qa_log_path: Path = None, client=None):
        self.profile = profile or {}
        self.overrides = self.profile.get("answers", {})
        self.models = [model or config.GEMINI_MODEL] + [
            m for m in (fallback_models if fallback_models is not None else config.GEMINI_FALLBACK_MODELS)
            if m != (model or config.GEMINI_MODEL)]
        self.cache_path = Path(cache_path or config.ANSWER_CACHE)
        self.qa_log_path = Path(qa_log_path or config.QA_LOG_CSV)
        self.cache = self._load_cache()
        self.client = client
        self._api_key = api_key
        self.calls = 0

        profile_for_prompt = {k: v for k, v in self.profile.items() if k != "answers"}
        self.system_instruction = SYSTEM_PROMPT + json.dumps(profile_for_prompt, ensure_ascii=False, indent=1)
        if self.overrides:
            self.system_instruction += (
                "\n\nFIXED ANSWERS (always prefer these when the question matches):\n"
                + json.dumps(self.overrides, ensure_ascii=False, indent=1))

    # ---------------------------------------------------------------- cache / log
    def _load_cache(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save answer cache: %s", exc)

    def _log_qa(self, question: str, options: Sequence[str], ans: Answer) -> None:
        new = not self.qa_log_path.exists()
        try:
            with self.qa_log_path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["timestamp", "question", "options", "answer", "source"])
                shown = ans.text if not ans.indexes else ",".join(
                    f"{i}:{options[i - 1]}" for i in ans.indexes if i <= len(options))
                w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), question,
                            " | ".join(options), shown, ans.source])
        except OSError:
            pass

    # ---------------------------------------------------------------- Gemini call
    def _client(self):
        if self.client is None:
            from google import genai          # imported lazily so the rest of the project works without it
            try:
                from google.genai import types
                self.client = genai.Client(
                    api_key=self._api_key,
                    http_options=types.HttpOptions(timeout=int(config.GEMINI_TIMEOUT_SECONDS * 1000)))
            except Exception:                 # noqa: BLE001 - older SDK without HttpOptions
                self.client = genai.Client(api_key=self._api_key)
        return self.client

    def _generate(self, model: str, prompt: str) -> str:
        """One raw API call (overridden in unit tests)."""
        from google.genai import types
        resp = self._client().models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=0.2, max_output_tokens=200))
        return (resp.text or "").strip()

    def _ask_model(self, prompt: str) -> str:
        """Try each model quickly: 2 attempts on a busy model, then move on.  Hard time limit per question."""
        deadline = time.time() + config.GEMINI_MAX_SECONDS_PER_QUESTION
        last_exc = None
        for model in self.models:
            for attempt in range(2):
                if time.time() > deadline:
                    raise RuntimeError(f"Gemini did not answer within {config.GEMINI_MAX_SECONDS_PER_QUESTION}s. "
                                       f"Last error: {str(last_exc)[:120]}")
                try:
                    text = self._generate(model, prompt)
                    self.calls += 1
                    return text
                except Exception as exc:          # noqa: BLE001 - SDK raises several types
                    last_exc = exc
                    msg = str(exc).lower()
                    if "api key" in msg or "api_key" in msg or "permission_denied" in msg or "unauthenticated" in msg:
                        raise RuntimeError(f"Gemini rejected the API key / permissions: {exc}") from exc
                    if "not found" in msg or "404" in msg or "no longer available" in msg:
                        log.warning("Gemini model '%s' is not available - trying the next one", model)
                        break                       # next model
                    # 503 overloaded / 429 rate limit / timeout: one short retry, then next model
                    if attempt == 0:
                        log.warning("Gemini '%s' busy (%s). Retrying once...", model, str(exc)[:60])
                        time.sleep(2)
                    else:
                        log.warning("Gemini '%s' still busy - switching model", model)
        raise RuntimeError(f"All Gemini models failed. Last error: {str(last_exc)[:200]}")

    # ---------------------------------------------------------------- public API
    def answer(self, question: str, options: Sequence[str] = (), multi: bool = False) -> Optional[Answer]:
        """Return an Answer, or None if we could not produce a trustworthy one."""
        question = (question or "").strip()
        options = [o.strip() for o in options]
        if not question:
            return None

        # 1) your fixed answers from profile.json
        fixed = find_override(question, self.overrides)
        if fixed is not None:
            if options:
                idx = match_option_by_text(fixed, options)
                if idx:
                    ans = Answer(text=options[idx - 1], indexes=[idx], source="profile")
                    self._log_qa(question, options, ans)
                    return ans
            else:
                ans = Answer(text=fixed, source="profile")
                self._log_qa(question, options, ans)
                return ans

        # 2) cache
        cache_key = normalize(question) + "||" + "|".join(normalize(o) for o in options) + ("||m" if multi else "")
        if cache_key in self.cache:
            c = self.cache[cache_key]
            return Answer(text=c.get("text", ""), indexes=c.get("indexes"), source="cache")

        # 3) Gemini
        skip_idx = {i for i, o in enumerate(options, 1) if normalize(o).startswith("skip")}
        if options:
            listing = "\n".join(f"{i}. {o}" for i, o in enumerate(options, 1) if i not in skip_idx or len(skip_idx) == len(options))
            kind = "MULTI-SELECT (pick all that apply)" if multi else "SINGLE CHOICE"
            prompt = f"Question: {question}\n{kind} options:\n{listing}\nReply with ONLY the option number(s)."
        else:
            prompt = f"Question: {question}\nReply with ONLY the answer."
        try:
            reply = self._ask_model(prompt)
        except RuntimeError as exc:
            log.error("%s", exc)
            return None
        if not reply:
            return None

        if options:
            idxs = [i for i in parse_indexes(reply, len(options), multi)
                    if i not in skip_idx or len(skip_idx) == len(options)]
            if not idxs:
                idx = match_option_by_text(reply, options)      # model answered with text instead of a number
                idxs = [idx] if idx else []
            if not idxs:
                log.warning("Could not map Gemini reply %r to any option", reply[:80])
                return None
            ans = Answer(text=", ".join(options[i - 1] for i in idxs), indexes=idxs)
        else:
            text = reply.strip().splitlines()[0].strip().strip('"\'` ').strip()
            ans = Answer(text=text)

        self.cache[cache_key] = {"text": ans.text, "indexes": ans.indexes}
        self._save_cache()
        self._log_qa(question, options, ans)
        return ans