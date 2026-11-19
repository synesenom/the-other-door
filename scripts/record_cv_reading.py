"""Spike of #429 (epic #428): how well does a small model read a CV and check a tailored CV's facts?

Measures Haiku, then Sonnet, on made-up data only (never a real CV): a *reader* task (cv.md in, what the CV says out:
section kinds, contacts, skill and language levels, name, email, city, country, working languages, role years, the
parts of each entry heading) and a *facts* task (a source cv.md and a tailored CV body with fabrications planted in
it; the model lists the claims the source does not back). Ground truth is built in: the corpus is generated from
made-up people, so every expected value is a literal of the text. The rules of today (`facts.check`, `cv_body.header`,
`_heading3`) are scored on the same cases as the baseline. A miss becomes a made-up prompt example, never a rule in
Python.

    poetry run python scripts/record_cv_reading.py --write-fixtures
    poetry run python scripts/record_cv_reading.py --task reader|facts --model haiku|sonnet [--runs 3] [--version N]
    poetry run python scripts/record_cv_reading.py --task report --model haiku|sonnet|baseline [--version N]

Answers are recorded under `tests/tailoring/fixtures/cv_reading/recorded/<model>/<task>/v<version>/<case>.<run>.json`
(raw, so the scoring unit test reads them offline). Calls go through `claude_cli.ask` on the local claude's plan (never
an API key); the usage feature keys are `infer_basics` (the reader) and `revise` (the fact check), the nearest
existing ones: this spike adds none.
"""

from __future__ import annotations

import re

REPO = None  # set below, after the imports a script needs


def _n(value) -> str:
    """A text for comparison: case, spacing and the kind of dash do not matter."""
    text = re.sub(r"[‐-―−]", "-", str(value or ""))
    text = re.sub(r"\s*-\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


# --- scoring the reader -----------------------------------------------------------------------------------------

READER_FIELDS = ("sections", "contacts", "levels", "name", "email", "city", "country", "languages", "years",
                 "heading_role", "heading_org", "heading_dates", "heading_place")
_WORKING = {"native", "fluent", "working"}


def _empty() -> dict:
    return {f: {"hit": 0, "total": 0} for f in READER_FIELDS}


def _count(score: dict, field: str, ok: bool) -> None:
    score[field]["total"] += 1
    score[field]["hit"] += bool(ok)


def score_reader(expected: dict, answer: dict) -> dict:
    """Per field, how many of the expected values the model's `answer` read right: `{field: {hit, total}}`. An answer
    that is an error misses everything."""
    answer = {} if not isinstance(answer, dict) or "error" in answer else answer
    score = _empty()
    for field in ("name", "email", "city", "country"):
        _count(score, field, answer.get(field) is not None and
               (str(answer[field]).strip() == str(expected[field]) if field in ("name", "email")
                else _n(answer[field]) == _n(expected[field])))
    kinds = {_n(s.get("heading")): s.get("kind") for s in answer.get("sections") or [] if isinstance(s, dict)}
    for heading, kind in expected["sections"].items():
        _count(score, "sections", kinds.get(_n(heading)) == kind)
    contacts = [c for c in answer.get("contacts") or [] if isinstance(c, dict)]
    for c in expected["contacts"]:
        _count(score, "contacts", any(
            a.get("kind") == c["kind"] and _n(a.get("label")) == _n(c["label"]) and _n(a.get("value")) == _n(c["value"])
            for a in contacts))
    levels = {_n(i.get("item")): i.get("level") for i in answer.get("levels") or [] if isinstance(i, dict)}
    for item, level in expected["levels"].items():
        _count(score, "levels", levels.get(_n(item)) == level)
    working = {l.get("language") for l in answer.get("languages") or []
               if isinstance(l, dict) and str(l.get("level")).lower() in _WORKING}
    _count(score, "languages", working == set(expected["working_languages"]))
    entries = {_n(e.get("heading")): e for e in answer.get("entries") or [] if isinstance(e, dict)}
    for want in expected["entries"]:
        got = entries.get(_n(want["heading"]), {})
        _count(score, "years", got.get("start_year") == want["start_year"])
        _count(score, "years", got.get("end_year") == want["end_year"])
        for part in ("role", "org", "dates", "place"):
            _count(score, f"heading_{part}", _n(got.get(part)) == _n(want[part]))
    return score
