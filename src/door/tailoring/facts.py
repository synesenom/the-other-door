"""The fact check of a tailored CV and cover letter against the candidate's own sources (#433).

Every number, year, employer, skill or tool, certification and degree in ``cv.html`` / ``cover_letter.html`` should
be backed by ``profile/cv.md`` or the story bank (the letter may also echo the ad). One Haiku call reads the sources and
both documents and lists what is not (`fact-checker.md`, `SCHEMA`: the spike's, recorded in `scripts/record_cv_reading.py`);
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
    return claude_cli.ask("fact-checker", inputs, feature="facts", schema=SCHEMA, effort="low", timeout_s=120)


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
        saved = _saved(self.output_dir)
        if saved and saved.get("inputs_sha") == key and saved.get("version") == VERSION:
            return {"version": VERSION, "answer": {"unsupported": saved["unsupported"]}}
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
        key, store = _key(inputs), _Store(output_dir)
        saved = (_saved(output_dir) or {}).get("unsupported")
        hit = load(output_dir, profile_dir) is not None
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


def _saved(output_dir: Path) -> dict | None:
    try:
        data = json.loads((output_dir / FACTS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("unsupported"), list) else None
    except (OSError, ValueError):
        return None


def load(output_dir: Path, profile_dir: Path) -> list[dict] | None:
    """The unsupported list `check` last wrote for the documents and sources as they are now (and this `VERSION`), or
    None (not checked) when it is missing or unreadable, has no `inputs_sha`, or was made for other inputs. Reads files
    only, no model: `load(...) is not None` is also "a `check` asks nothing"."""
    gathered = _gather(output_dir, profile_dir)
    record = _Store(output_dir).read(_key(gathered[0])) if gathered else None
    return record["answer"]["unsupported"] if record else None
