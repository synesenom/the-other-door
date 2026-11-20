"""The fact check of a tailored CV and cover letter against the candidate's own sources (#433).

Every number, year, employer, skill or tool, certification and degree in ``cv.html`` / ``cover_letter.html`` should
be backed by ``profile/cv.md`` or the story bank (the letter may also echo the ad). One Haiku call reads the sources and
both documents and lists what is not (`PROMPT`, `SCHEMA`: the spike's, recorded in `scripts/record_cv_reading.py`);
code keeps a finding only when its `context` is a stretch of the text of the document it names (`is_verbatim`), and adds
each `TODO` (the app's own marker of a gap of cv.md's). What is found is *reported*, never blocked. The answer is cached
in ``facts.json`` under the sha256 of everything the model was shown (`core/ask_cached`), so the same inputs are never
asked twice. A check that cannot run (no CV, a failed call) is None: there is no fallback to rules.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from door.core import ask_cached, claude_cli, utils
from door.render import html_doc

FACTS_FILE = "facts.json"
VERSION = 1  # bump with the prompt, the schema or the check: a cached answer of another version is asked again
KINDS = ("number", "year", "employer", "skill", "certification", "degree")
_CONTEXT_CHARS = 200  # the longest context a TODO line is kept at
_TODO_RE = re.compile(r"\bTODO\b")
_FILES = {"cv": "cv", "letter": "cover_letter"}  # the schema's name of a document, and the name `facts.json` keeps

PROMPT = (
    "You check a tailored CV and cover letter against the candidate's own sources. You get the SOURCE CV (markdown), "
    "the STORY BANK (stories of the candidate, or none), the POSTING (the job ad, or none), the TAILORED CV (HTML) and "
    "the COVER LETTER (HTML, or none). The tailored documents may drop, reorder, merge, shorten and reword, and may be "
    "written in another language than the source (headings, degrees, months and level words translated; names, employers "
    "and figures are not); they must not add a fact the sources do not back. A fact the story bank backs is supported; "
    "the cover letter may also echo the posting's words, figures and skills. List every claim the sources do not "
    "support:\n"
    "- `number`: a figure, amount, percentage or count whose VALUE differs from the sources'; a figure told another way "
    "with the same value (`1 200 000 EUR` and `1,2 M EUR`, `40 000` and `40k`, `9 %` and `9 percent`, a number written "
    "in words) is supported. The day and month of a date are not figures.\n"
    "- `year`: a year, or a year of a date range, that differs from the source's; a date written another way "
    "(`03/2019`, `1.3.2019`, `2019-03`, `1st March 2019`) is the same date.\n"
    "- `employer`: an employer the sources do not name. `skill`: a tool, technology or method they do not name; a name of "
    "one the source backs written another way (`PowerBI` for `Power BI`) is supported. `certification`, `degree`: one "
    "they do not name, in whatever language it is written.\n"
    "Ignore the header, the contact details, the recipient, the date, the greeting and the closing. `file`: `cv` or "
    "`letter`. `value`: the claimed value. `context`: a stretch of that document's text, copied exactly as it reads (at "
    "most 15 words) that holds it. List nothing the sources support: an empty list is a clean document.\n"
    "Examples (made up):\n"
    "- `context` is plain text with no HTML tag in it: for `<li><strong>Rust</strong></li>` it is `Rust`, for a heading "
    "`<span class=\"role\">Analyst</span> | <span class=\"org\">Zenith Corp</span>` it is `Analyst | Zenith Corp`.\n"
    "- `value` is the claimed item alone, as the document writes it: a figure with its unit (`3 k`, `7 percent`), the name "
    "of an employer, skill, certification or degree. For a changed date range `2004 - 2008` the kind is `year` and the "
    "value the one year that differs (`2004`), not the range.\n"
    "- Never copy markup into `context`: `<strong>Rust</strong>` is wrong and `Rust` is right; "
    "`<span class=\"dates\">2004 - 2008</span>` is wrong and `Zenith Corp - 2004 - 2008` is right. Copy only words and "
    "figures, as the text of the page reads them.\n"
    "- A degree translated is the same degree, and so is its local title: `BSc in Physics`, `Licence de physique` and "
    "`Bachelor i fysik` are one degree, and `MSc in Chemistry`, `Master en chimie` and `Cand.scient. i kemi` are one. "
    "Compare the level and the field, not the words.\n"
    "- `value` of a count or an amount is the figure with its unit sign or currency and nothing after it: `7 k`, `12 %`, "
    "`3 M EUR`; for `a team of 7 people` it is `7`.\n"
    "- A tool, skill or figure that only the story bank names is supported: a story that says `I used Rust` backs `Rust` in the "
    "tailored CV.\n"
    "- For a bold list item `<li><strong>Rust</strong> \u2014 2020</li>` the `context` is `Rust \u2014 2020`: the words of the item, "
    "no tag.\n"
    "- A year or date the source gives for a job is supported wherever the tailored text puts it: `(2005)` after a bullet of "
    "a job the source says began in 2005 is no new year; a year in brackets at the end of a bullet is that date, not a claim.\n"
    "Answer with the JSON only."
)

SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": list(KINDS)}, "file": {"type": "string", "enum": list(_FILES)},
        "value": {"type": "string"}, "context": {"type": "string"}}, "required": ["kind", "file", "value", "context"]}}},
    "required": ["findings"],
}


class FactsError(ValueError):
    """The check could not be made: the call failed or its answer does not hold."""


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_verbatim(quote: str, *bodies: str) -> bool:
    """The quote is a stretch of the text of one of the bodies (spacing squashed: a no-break space, a line break)."""
    quote = _squash(quote or "")
    return bool(quote) and any(quote in _squash(html_doc.text(b)) for b in bodies if b)


def input_text(cv_md: str, story: str, posting: str, cv_html: str, letter_html: str) -> str:
    """What the model is shown: the sources, the posting and the two documents."""
    return (f"SOURCE CV:\n<<<\n{cv_md}\n>>>\n\nSTORY BANK:\n<<<\n{story or 'none'}\n>>>\n\n"
            f"POSTING:\n<<<\n{posting or 'none'}\n>>>\n\nTAILORED CV:\n<<<\n{cv_html}\n>>>\n\n"
            f"COVER LETTER:\n<<<\n{letter_html or 'none'}\n>>>\n")


def _ask(inputs: str) -> dict:
    """The one model call: Haiku at low effort with no MCP servers."""
    return claude_cli.ask(PROMPT, inputs, model="haiku", feature="facts", schema=SCHEMA, effort="low", timeout_s=120)


def _placeholders(body: str, file: str) -> list[dict]:
    """Each `TODO` in the text of `body`, the header included: a gap of cv.md's that must not reach a document."""
    return [{"kind": "placeholder", "value": "TODO", "context": line[:_CONTEXT_CHARS], "file": file}
            for line in map(_squash, html_doc.text(body).splitlines()) if _TODO_RE.search(line)]


def _findings(answer: dict, bodies: dict[str, str]) -> list[dict]:
    """The model's findings (`SCHEMA`'s shape) whose `context` is text of the document they name, each kind, value and
    file once, then each `TODO`; `{kind, value, context, file}` with the file as `facts.json` names it."""
    out, seen = [], set()
    for item in answer.get("findings") or []:
        file = _FILES.get(item.get("file"))
        key = (item.get("kind"), item.get("value"), file)
        if not item.get("value") or key in seen or not is_verbatim(item.get("context"), bodies.get(file, "")):
            continue
        seen.add(key)
        out.append({"kind": item["kind"], "value": item["value"], "context": item["context"], "file": file})
    for file, body in bodies.items():
        out += _placeholders(body, file) if body else []
    return out


def _asked(inputs: str, bodies: dict[str, str]) -> dict:
    """The model's answer as the `unsupported` list it makes; a reply of another shape than `SCHEMA` is a FactsError."""
    try:
        return {"unsupported": _findings(_ask(inputs), bodies)}
    except (AttributeError, KeyError, TypeError) as exc:
        raise FactsError(f"the answer is not of the schema's shape: {exc}") from None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


_REASON_MAX = 200


def _clean_reason(value: object) -> str | None:
    """A reason as one short line of plain text, or None when it is not a non-empty string."""
    if not isinstance(value, str):
        return None
    text = _squash("".join(" " if ch.isspace() or not ch.isprintable() else ch for ch in value))
    return text[:_REASON_MAX].rstrip() or None


def _item_key(item: dict) -> tuple:
    return (item.get("kind"), item.get("value"), item.get("file"))


def _with_reasons(found: list[dict], saved: list | None, keep: list[dict] | None) -> None:
    """Put on each flagged item (not a placeholder) the reason recorded for it before, then the ``keep`` ones."""
    reasons: dict[tuple, str] = {}
    for source in (saved or [], keep or []):
        for item in source:
            if isinstance(item, dict) and (reason := _clean_reason(item.get("reason"))):
                reasons[_item_key(item)] = reason
    for item in found:
        if item.get("kind") != "placeholder" and (reason := reasons.get(_item_key(item))):
            item["reason"] = reason



class _Store:
    """`facts.json` as the cache of `ask_cached`: one record, for the one key (the sha256 of the inputs) and `VERSION`
    it was made for."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def read(self, key: str):
        try:
            data = json.loads((self.output_dir / FACTS_FILE).read_text(encoding="utf-8"))
            if data["inputs_sha"] == key and data["version"] == VERSION and isinstance(data["unsupported"], list):
                return {"version": data["version"], "answer": {"unsupported": data["unsupported"]}}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def write(self, key: str, record: dict) -> None:
        pass  # `check` writes the file once, with the reasons applied

    def drop(self, key: str) -> None:
        pass  # the record is replaced by the next write


def _held(answer: dict, bodies: dict[str, str]) -> list[dict]:
    """The cached `unsupported` list when every finding in it still holds to the text, else FactsError."""
    items = answer.get("unsupported")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise FactsError("the cached findings are not a list")
    for item in items:
        if item.get("kind") != "placeholder" and not is_verbatim(item.get("context"), bodies.get(item.get("file"), "")):
            raise FactsError(f"{item.get('value')!r} is not in the text any more")
    return items


def _gather(output_dir: Path, profile_dir: Path) -> tuple[str, dict[str, str]] | None:
    """What the model is shown for this job, and the text of each document, or None with no ``cv.md`` or ``cv.html``."""
    cv_md, cv_html = _read(profile_dir / "cv.md"), _read(output_dir / "cv.html")
    if not cv_md or not cv_html:
        return None
    letter = _read(output_dir / "cover_letter.html")
    try:
        posting = json.loads(_read(output_dir / "posting.json") or "{}")
    except ValueError:
        posting = {}
    posting = posting if isinstance(posting, dict) else {}
    ad = "\n".join(str(posting.get(k) or "") for k in ("title", "description")).strip()
    return (input_text(cv_md, _read(profile_dir / "story_bank.md"), ad, cv_html, letter),
            {"cv": cv_html, "cover_letter": letter})


def _key(inputs: str) -> str:
    return hashlib.sha256(inputs.encode("utf-8")).hexdigest()


def is_cached(output_dir: Path, profile_dir: Path) -> bool:
    """``facts.json`` already holds the answer for what `check` would show the model now: a `check` asks nothing."""
    gathered = _gather(output_dir, profile_dir)
    return gathered is not None and _Store(output_dir).read(_key(gathered[0])) is not None


def check(
    output_dir: Path,
    profile_dir: Path,
    *,
    write: bool = True,
    keep: list[dict] | None = None,
) -> list[dict] | None:
    """Check ``output_dir``'s CV and letter against the profile; None when it cannot be known.

    ``[]`` is clean. Asks the model once for these inputs (the answer is cached in ``facts.json``, which is written
    unless ``write`` is False, and the same inputs ask nothing); None, with nothing written, when there is no
    ``cv.md`` or ``cv.html`` or the call failed (the problem log has it). Never raises.
    An item still flagged keeps the ``reason`` recorded for it (by kind, value and file); ``keep``
    (``[{kind, value, file, reason}]``) records new ones. A TODO never takes one.
    """
    try:
        gathered = _gather(output_dir, profile_dir)
        if gathered is None:
            return None
        inputs, bodies = gathered
        key, saved, store = _key(inputs), load(output_dir), _Store(output_dir)
        hit = store.read(key) is not None
        found = ask_cached.cached_answer(
            key=key, version=VERSION, label="facts",
            ask=lambda: _asked(inputs, bodies), check=lambda answer: _held(answer, bodies),
            error=FactsError, unreached=lambda exc: FactsError(str(exc)), store=store)
    except FactsError:  # a check that cannot run is "not checked", never a failure (the problem log has why)
        return None
    found = [dict(item) for item in found]
    _with_reasons(found, saved, keep if isinstance(keep, list) else None)
    if write and not (hit and found == saved):
        payload = {"checked_at": datetime.now(timezone.utc).isoformat(), "unsupported": found,
                   "inputs_sha": key, "version": VERSION}
        try:
            utils.write_json_atomic(output_dir / FACTS_FILE, payload, default=None)
        except OSError:
            pass
    return found


def load(output_dir: Path) -> list[dict] | None:
    """The unsupported list `check` last wrote, or None when missing or unreadable."""
    try:
        data = json.loads((output_dir / FACTS_FILE).read_text(encoding="utf-8"))
        items = data["unsupported"]
        return items if isinstance(items, list) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
