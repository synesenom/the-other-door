"""One reading of cv.md (#430, epic #428): what the CV says, read by one Haiku call instead of by word lists.

`read(cv_md)` is the one reader every caller maps from (`infer_basics`, `find`'s skill terms, the salary estimate, the
draft's skills headings): sections by kind, contact details, skills, levels, name, email, city, country, languages and each
`###` entry's parts and years, in any language. The model's answer is held to what code can verify (the headings are
real `## ` and `### ` lines and none is left out, every value is text of the CV, enums and years hold), asked once more
when it does not hold, and only then cached by the sha256 of the CV's text under `HOME/.cv_read/`. A failed call or an
answer that does not hold is a `CvReadError` in words: there is never a fallback to rules. The prompt and schema are
the spike's (`scripts/record_cv_reading.py`), so its recorded answers stay valid.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from door.core import ask_cached, claude_cli, workspace

PROMPT_VERSION = 2  # bump with the prompt, the schema or the check: a cached answer of another version is asked again
KINDS = ("summary", "experience", "skills", "education", "certifications", "languages", "interests", "other")
CONTACT_KINDS = ("phone", "email", "web", "linkedin", "github", "location")
LEVELS = ("native", "fluent", "working", "conversational", "basic")
_MARKER = re.compile(r"\s*<!--.*?-->\s*$")


_STR_OR_NULL = {"type": ["string", "null"]}
_INT_OR_NULL = {"type": ["integer", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "name": _STR_OR_NULL, "email": _STR_OR_NULL, "city": _STR_OR_NULL, "country": _STR_OR_NULL,
        "languages": {"type": "array", "items": {"type": "object", "properties": {"language": {"type": "string"}, "code": {"type": "string"}, "level": {"enum": list(LEVELS)}},
                                                 "required": ["language", "code", "level"]}},
        "sections": {"type": "array", "items": {"type": "object", "properties": {"heading": {"type": "string"}, "kind": {"type": "string"}},
                                                "required": ["heading", "kind"]}},
        "contacts": {"type": "array", "items": {"type": "object", "properties": {"kind": {"type": "string"}, "label": _STR_OR_NULL, "value": {"type": "string"}},
                                                "required": ["kind", "label", "value"]}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "levels": {"type": "array", "items": {"type": "object", "properties": {"item": {"type": "string"}, "level": _INT_OR_NULL},
                                              "required": ["item", "level"]}},
        "entries": {"type": "array", "items": {"type": "object", "properties": {
            "heading": {"type": "string"}, "role": _STR_OR_NULL, "org": _STR_OR_NULL, "dates": _STR_OR_NULL, "place": _STR_OR_NULL,
            "start_year": _INT_OR_NULL, "end_year": _INT_OR_NULL}, "required": ["heading", "role", "org", "dates", "place", "start_year", "end_year"]}},
    },
    "required": ["name", "email", "city", "country", "languages", "sections", "contacts", "skills", "levels", "entries"],
}


class CvReadError(ValueError):
    """The CV could not be read: the call failed or its answer did not hold. The message is in plain words."""


class CvUnreached(CvReadError):
    """The call itself failed (`claude` timed out, signed out, no answer): nothing in the CV to fix."""


def _normalise(cv_md: str) -> str:
    """The CV as it is read and cached: line endings made `\\n`, the text stripped, each line's trailing space dropped."""
    return "\n".join(line.rstrip() for line in (cv_md or "").replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))


def _empty() -> dict:
    """The reading of a CV with nothing in it."""
    return {"name": None, "email": None, "city": None, "country": None, "languages": [], "sections": [],
            "contacts": [], "skills": [], "levels": [], "entries": []}


def squash(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def _lines(md: str, prefix: str) -> list[str]:
    """The text after `prefix` of each line that starts with it (`## `, `### `), a trailing `<!-- -->` comment dropped."""
    return [_MARKER.sub("", line[len(prefix):]).strip() for line in md.split("\n") if line.startswith(prefix)]


def lines_by_kind(md: str, reading: dict):
    """`(kind, line)` for each line of `md`: the kind the reading gives the `## ` section it is in (a heading is in its own),
    `None` before the first heading or where the reading has no such section."""
    kinds = [s.get("kind") for s in reading.get("sections") or []]
    section = -1
    for line in (md or "").splitlines():
        if line.startswith("## "):
            section += 1
        yield (kinds[section] if 0 <= section < len(kinds) else None), line


def check(answer, md: str) -> dict:
    """`answer` held to what the code can verify of the CV `md` (normalised): the `## ` headings are the CV's own, in order and
    none left out, the `### ` headings are real lines and each entry's parts sit in its own, every value is text of the CV, enums and years hold.

    Returns:
        The answer, unchanged, when it holds.

    Raises:
        CvReadError: it does not hold; `detail` of the message says what.
    """
    squashed = squash(md)

    def fail(what: str):
        raise CvReadError(f"The reading of your CV did not hold ({what}).")

    def text(value, what: str, *, allow_none: bool = True) -> None:
        if value is None and allow_none:
            return
        if not isinstance(value, str) or not value.strip() or squash(value) not in squashed:
            fail(f"{what} {str(value)[:40]!r} is not in the CV")

    def items(key: str) -> list:
        value = answer.get(key)
        if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
            fail(f"`{key}` is not a list")
        return value

    if not isinstance(answer, dict):
        fail("not an object")
    for key in ("name", "email", "city"):
        text(answer.get(key), key)
    country = answer.get("country")
    if country is not None and not (isinstance(country, str) and re.fullmatch(r"[a-z]{2}", country)):
        fail("country is not an ISO code")

    sections = items("sections")
    if [squash(_MARKER.sub("", s.get("heading") or "")) for s in sections] != [squash(h) for h in _lines(md, "## ")]:
        fail("the sections are not the CV's own `##` lines")
    if any(s.get("kind") not in KINDS for s in sections):
        fail("a section has no kind")

    for c in items("contacts"):
        if c.get("kind") not in CONTACT_KINDS:
            fail("a contact has no kind")
        text(c.get("label"), "label")
        text(c.get("value"), "contact", allow_none=False)

    skills = answer.get("skills")
    if not isinstance(skills, list):
        fail("`skills` is not a list")
    for skill in skills:
        text(skill, "skill", allow_none=False)

    for lv in items("levels"):
        text(lv.get("item"), "level item", allow_none=False)
        level = lv.get("level")
        if level is not None and not (isinstance(level, int) and not isinstance(level, bool) and 1 <= level <= 5):
            fail("a level is not 1 to 5")

    for lang in items("languages"):
        text(lang.get("language"), "language", allow_none=False)
        if not (isinstance(lang.get("code"), str) and re.fullmatch(r"[a-z]{2}", lang["code"])):
            fail("a language has no ISO code")
        if lang.get("level") not in LEVELS:
            fail("a language has no level")

    real = {squash(h) for h in _lines(md, "### ")}
    for entry in items("entries"):
        if squash(entry.get("heading") or "") not in real:
            fail(f"entry {str(entry.get('heading'))[:40]!r} is not a `###` line")
        for key in ("role", "org", "dates", "place"):
            text(entry.get(key), key)
            if entry.get(key) is not None and squash(entry[key]) not in squash(entry["heading"]):
                fail(f"entry {key} {str(entry[key])[:40]!r} is not in its own `###` line")
        for key in ("start_year", "end_year"):
            year = entry.get(key)
            if year is None:
                continue
            if not isinstance(year, int) or isinstance(year, bool) or str(year) not in (entry.get("dates") or ""):
                fail(f"year {year} is not in the entry's dates")
    return answer


# ---------- the call and its cache ----------

def _cache_dir() -> Path:
    return workspace.HOME / ".cv_read"


def _ask(md: str) -> dict:
    """The one model call: Haiku at low effort with no MCP servers."""
    return claude_cli.ask("cv-reader", f"CV:\n<<<\n{md}\n>>>\n", feature="cv_read", schema=SCHEMA,
                          effort="low", timeout_s=120)


def read(cv_md: str) -> dict:
    """The checked reading of `cv_md`: the cached one for its normalised text and this `PROMPT_VERSION` when it still holds,
    else one Haiku call (`_ask`) whose answer is checked and then cached (`ask_cached`); an answer that does not hold is
    asked once more (the model's answers vary). A CV with nothing in it is read without a call.

    Raises:
        CvReadError: the call failed or its answer did not hold; nothing is cached then. There is no fallback.
    """
    md = _normalise(cv_md)
    if not md:
        return _empty()
    return ask_cached.cached_answer(
        key=hashlib.sha256(md.encode("utf-8")).hexdigest(), version=PROMPT_VERSION, ask=lambda: _ask(md),
        check=lambda answer: check(answer, md), error=CvReadError,
        unreached=lambda exc: CvUnreached(f"Your CV could not be read: {exc}"), label="cv read",
        store=ask_cached.DirStore(_cache_dir()))
