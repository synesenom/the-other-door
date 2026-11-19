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

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from door.render import html_doc  # noqa: E402
from door.tailoring import facts  # noqa: E402


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


# --- scoring the facts check ------------------------------------------------------------------------------------

KINDS = ("number", "year", "employer", "skill", "certification", "degree")


def _val(value) -> str:
    """A claimed value for comparison: ``1,8 M kr`` and ``1.8M kr`` are one."""
    return re.sub(r"\s+", "", _n(value)).replace(",", ".")


def is_verbatim(quote: str, body_html: str) -> bool:
    """The quote is a stretch of the body's text (spacing squashed, as `facts` squashes it)."""
    quote = facts._squash(quote or "")
    return bool(quote) and quote in facts._squash(html_doc.text(body_html))


def _findings(answer) -> list[dict]:
    return [f for f in answer if isinstance(f, dict)] if isinstance(answer, list) else []


def _matches(plant: dict, found: dict) -> bool:
    if found.get("kind") != plant["kind"]:
        return False
    context = _val(found.get("context"))
    return (_val(found.get("value")) == _val(plant["planted_value"]) or _val(plant["planted_value"]) in context
            or _val(plant["quote"]) in context)


def score_facts(plants: list[dict], findings, body_html: str) -> dict:
    """One body's reading: `per_kind` {kind: {planted, found}} for the kinds planted, `false_flags` (findings that
    match no plant), `verbatim` (findings whose context is in the body, of all findings). An error answer finds nothing."""
    found = _findings(findings)
    per_kind: dict = {}
    for plant in plants:
        cell = per_kind.setdefault(plant["kind"], {"planted": 0, "found": 0})
        cell["planted"] += 1
        cell["found"] += any(_matches(plant, f) for f in found)
    false = sum(not any(_matches(p, f) for p in plants) for f in found)
    return {"per_kind": per_kind, "false_flags": false,
            "verbatim": (sum(is_verbatim(f.get("context"), body_html) for f in found), len(found))}


def stability(runs: dict) -> float:
    """The share of bodies whose set of (kind, value) flags is the same in every run (`runs`: case to each run's findings)."""
    same = [len({frozenset((f.get("kind"), _val(f.get("value"))) for f in _findings(r)) for r in rs}) == 1
            for rs in runs.values()]
    return sum(same) / len(same) if same else 0.0


# --- the go thresholds of #429 ----------------------------------------------------------------------------------

FACTS_GO = {"recall": 0.90, "false_clean_max": 1, "verbatim": 0.98, "stable": 0.95}
FACTS_NO_GO = {"recall": 0.80, "false_clean_max": 2}
READER_GO = {"sections": 0.98, "contacts": 0.98, "name": 1.0, "email": 1.0, "years": 0.95}
READER_NO_GO = 0.80


def facts_verdict(report: dict) -> str:
    """`go`, `no-go` or `close` for a facts report: `per_kind` recall, `false_clean_max` (most false flags on a clean
    body), `verbatim` and `stable` shares."""
    recalls = list(report["per_kind"].values())
    if min(recalls) < FACTS_NO_GO["recall"] or report["false_clean_max"] > FACTS_NO_GO["false_clean_max"]:
        return "no-go"
    ok = (min(recalls) >= FACTS_GO["recall"] and report["false_clean_max"] <= FACTS_GO["false_clean_max"]
          and report["verbatim"] >= FACTS_GO["verbatim"] and report["stable"] >= FACTS_GO["stable"])
    return "go" if ok else "close"


def reader_verdict(report: dict) -> str:
    """`go`, `no-go` or `close` for a reader report (a share per gated field)."""
    if any(report[f] < READER_NO_GO for f in READER_GO):
        return "no-go"
    return "go" if all(report[f] >= t for f, t in READER_GO.items()) else "close"
