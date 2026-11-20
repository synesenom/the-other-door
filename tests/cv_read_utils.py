"""The model's reading of cv.md (#430), for tests: no test reaches a model.

`fake_ask(md)` is the stand-in the autouse fixture of `tests/conftest.py` puts where `core/cv_read` asks. A CV the spike
recorded (`tests/tailoring/fixtures/cv_reading/*/reader/`, made-up CVs, answered by Haiku) gets its recorded answer; any
other CV gets a plain-format reading (the name is the `# ` line, the sections the `## ` lines, a skills list the items
under an English `Skills` heading, the contact line's `**Label:** value` parts, the entries the `### ` lines with the
years of their first date range). It holds no word list of any language but a few English labels, so a test that needs
more passes its own reading: `reading(md, skills=[...], sections={...})` is the plain reading with those keys replaced.
"""

import functools
import hashlib
import json
import re

from door.core import claude_cli, cv_read
from paths import TESTS_DIR

RECORDED = TESTS_DIR / "tailoring" / "fixtures" / "cv_reading"
_SECTION_KINDS = {
    "profile": "summary", "summary": "summary", "experience": "experience", "work experience": "experience",
    "education": "education", "skills": "skills", "technical skills": "skills", "certifications": "certifications",
    "languages": "languages", "interests": "interests",
}
_CONTACT_KINDS = {"phone": "phone", "email": "email", "e-mail": "email", "web": "web", "website": "web",
                  "linkedin": "linkedin", "github": "github", "location": "location"}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RANGE = re.compile(r"\b((?:19|20)\d\d)\s*[-–—]\s*((?:19|20)\d\d|[^\W\d_]+)", re.UNICODE)


@functools.cache
def _recorded() -> dict:
    found = {}
    for path in RECORDED.glob("*/reader/*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        found[data["key"]] = data["answer"]
    return found


def _key(md: str) -> str:
    return hashlib.sha256((claude_cli.prompt("cv-reader") + "\0" + f"CV:\n<<<\n{md}\n>>>\n").encode()).hexdigest()[:12]


def plain(md: str) -> dict:
    """The plain-format reading of the normalised CV `md`."""
    lines = md.split("\n")
    reading = cv_read._empty()
    reading["name"] = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), None)
    reading["email"] = next((m.group(0) for ln in lines if not ln.startswith(">") and (m := _EMAIL.search(ln))), None)
    kind = None
    for ln in lines:
        if ln.startswith("## "):
            heading = re.sub(r"\s*<!--.*?-->\s*$", "", ln[3:]).strip()
            kind = _SECTION_KINDS.get(heading.casefold(), "other")
            reading["sections"].append({"heading": heading, "kind": kind})
        elif ln.startswith("### "):
            heading = ln[4:].strip()
            m = _RANGE.search(heading)
            reading["entries"].append({
                "heading": heading, "role": None, "org": None, "dates": m.group(0) if m else None, "place": None,
                "start_year": int(m.group(1)) if m else None,
                "end_year": int(m.group(2)) if m and m.group(2).isdigit() else None})
        elif kind == "skills" and ln.strip():
            for item in re.split(r"[,;]", ln.strip().lstrip("-*• ")):
                if item.strip() and "<!--" not in item and item.strip() not in reading["skills"]:
                    reading["skills"].append(item.strip())
        elif kind is None and ln.startswith("**"):
            for part in ln.split("|"):
                m = re.match(r"\s*\*\*([^:*]+):\*\*\s*(.+?)\s*$", part)
                if m and (ckind := _CONTACT_KINDS.get(m.group(1).strip().casefold())):
                    reading["contacts"].append({"kind": ckind, "label": m.group(1).strip(), "value": m.group(2)})
                    if ckind == "location" and not reading["city"]:
                        reading["city"] = m.group(2)
    return reading


def fake_ask(md: str) -> dict:
    return _recorded().get(_key(md)) or plain(md)


def reading(md: str, **replace) -> dict:
    """The plain (or recorded) reading of `md`, with the keys in `replace` set."""
    return {**fake_ask(cv_read._normalise(md)), **replace}
