"""Turn the live smoke run's JUnit XML into a status page, one list per dimension.

The live-smoke workflow runs ``./scripts/run-test.sh --live --junitxml=...``
and then this script, which writes docs/badges/live-smoke.md. Each dimension is checked on its own,
so each has its own list:

- **Boards:** the boards (``Site.board``);
- **Employer feeds:** the other sites (``Site.config_key``);
- **Matcher:** every golden scoring case (``tests/matching/fixtures/golden/``), from
  ``tests/matching/test_matcher_golden.py``'s ``[<case>]`` runs (the real scorer on a Claude plan).

Each row is ✅ (its smoke tests passed), ❌ changed (one failed or errored: the site answered, but not as
the scraper reads it), ⛔ not reached (its test was skipped as ``not reached:``, ``tests/live_utils.py``: the
site refused the request or could not be reached), ❓ (not run, or skipped for another reason) or ➖ (it has
no live test; ``tests/live_matrix.NO_LIVE_TEST`` says why).

A row this run did not check (❓) keeps its last result from the page already at <out.md>, with the date
of the run that checked it: CI has no Claude plan and skips the golden set, so it keeps the matcher's last
local result; and a local run of some sites alone keeps the others' last CI result, so a site that refuses
GitHub's runners is checked by running its live test locally and this script without ``--run-url``. A row
not reached says how many runs in a row it was not and its last result before (``not reached 2 runs in a
row; last ✅ 2026-11-02``); with ``--unreached FILE`` the rows not reached for ``UNREACHED_RUNS`` runs in a
row are written to FILE (empty when none), which the workflow turns into an issue of their own: only a
change fails the run and opens the failure issue.

With ``--badges DIR`` it also writes one badge per list into DIR (``live-boards.svg``,
``live-feeds.svg``, ``live-matcher.svg``): "boards | 3/3", how
many passed of how many, green when every one passed, red when one changed, and orange when one was not
reached, not checked or has no live test. The badges are committed SVGs rather than GitHub's workflow badge URL, which can only say whether the
whole run passed.

Usage:  python scripts/smoke_report.py <junit.xml> <out.md> [--badges DIR] [--run-url URL] [--date YYYY-MM-DD]
                                     [--unreached FILE]
"""

import argparse
import datetime
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

_REPO = pathlib.Path(__file__).resolve().parent.parent
_SITE_TEST = re.compile(r"(?:^|\.)test_(\w+)_live$")
_PARAM_TEST = re.compile(r"\[([\w-]+)\]$")
_SYMBOLS = {"pass": "✅", "fail": "❌", "unreached": "⛔", "unknown": "❓", "none": "➖"}
_STATUS_OF = {symbol: status for status, symbol in _SYMBOLS.items()}
_ROW = re.compile(r"^\| (.+?) \| (\S+) \|(?: ([\d-]*) \|)?(?: (.*?) \|)?$")
_STREAK = re.compile(r"not reached (\d+) runs? in a row(?:; last (\S+) (\d{4}-\d{2}-\d{2}))?")
# The skip message of a live test whose site was not reached (tests/live_utils.NOT_REACHED).
_NOT_REACHED = "not reached:"
# A row not reached this many runs in a row is flagged on its own (--unreached).
UNREACHED_RUNS = 3
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LAST_RUN = re.compile(r"^Last \[workflow run\]\(\S+\): \d{4}-\d{2}-\d{2}\.", re.M)
_NO_RUN = re.compile(r"^No workflow run yet \(\d{4}-\d{2}-\d{2}\)\.", re.M)
_LAST_CHECKED = re.compile(r"^Last checked: (\d{4}-\d{2}-\d{2})\.$")
# Each list's badge: (its file, its label), by the list's title on the page.
_DIMENSION_BADGES = {
    "Boards": ("live-boards.svg", "boards"),
    "Employer feeds": ("live-feeds.svg", "employer feeds"),
    "Matcher": ("live-matcher.svg", "matcher"),
}
_GOLDEN_PREFIX = "golden-"


def golden_case_ids() -> list[str]:
    """The golden scoring cases, by their posting's id without its ``golden-`` prefix (the test's parameter)."""
    paths = sorted((_REPO / "tests" / "matching" / "fixtures" / "golden").glob("*.json"))
    ids = [json.loads(p.read_text(encoding="utf-8"))["posting"]["id"] for p in paths]
    return [i.removeprefix(_GOLDEN_PREFIX) for i in ids]


def _has_live_test(name: str) -> bool:
    return any((_REPO / "tests").rglob(f"test_{name}_live.py"))


def sections(xml: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """The page's lists, in order: ``[(title, [(label, status), ...]), ...]``."""
    sys.path.insert(0, str(_REPO / "src"))
    from door.core.sites import SITES

    boards = [n for n, s in SITES.items() if s.board]
    feeds = [n for n, s in SITES.items() if not s.board]

    def site_rows(names: list[str]) -> list[tuple[str, str]]:
        outcomes = site_outcomes(xml, names)
        return [(n, outcomes[n] if _has_live_test(n) else "none") for n in names]

    golden = golden_case_ids()
    by_case = param_outcomes(xml, "test_matcher_golden", golden)
    return [
        ("Boards", site_rows(boards)),
        ("Employer feeds", site_rows(feeds)),
        ("Matcher", [(case, by_case[case]) for case in golden]),
    ]


def _fold(case: ET.Element, current: str) -> str:
    """One more test case of a row: a failure or error is a change, whatever else ran; a pass beats a skip;
    a skip as not reached beats a row nothing else checked."""
    if current == "fail" or case.find("failure") is not None or case.find("error") is not None:
        return "fail"
    skipped = case.find("skipped")
    if skipped is None:
        return "pass"
    if current == "unknown" and (skipped.get("message") or "").startswith(_NOT_REACHED):
        return "unreached"
    return current


def site_outcomes(junit_xml: str, sites: list[str]) -> dict[str, str]:
    """Map each site to "pass", "fail", "unreached" or "unknown" from a pytest JUnit report.

    A site's (or discovery source's) tests live in ``tests/scrapers/<boards|discovery|feeds>/test_<site>_live.py``, matched by file name. Any failure or error
    fails the site; one that passed passes it; one skipped as not reached makes it not reached; a site whose
    tests were all skipped otherwise, or that has none in the report, is unknown.
    """
    outcomes = {site: "unknown" for site in sites}
    for case in ET.fromstring(junit_xml).iter("testcase"):
        match = _SITE_TEST.search(case.get("classname", ""))
        if not match or match.group(1) not in outcomes:
            continue
        site = match.group(1)
        outcomes[site] = _fold(case, outcomes[site])
    return outcomes


def param_outcomes(junit_xml: str, module: str, keys: list[str]) -> dict[str, str]:
    """Map each key to "pass", "fail", "unreached" or "unknown" from the runs of *module*'s parametrised test,
    whose parameter is the key (``test_golden_case[domain-mismatch]``)."""
    outcomes = {key: "unknown" for key in keys}
    for case in ET.fromstring(junit_xml).iter("testcase"):
        classname = case.get("classname", "")
        match = _PARAM_TEST.search(case.get("name", ""))
        if not (classname == module or classname.endswith("." + module)) or not match or match.group(1) not in outcomes:
            continue
        key = match.group(1)
        outcomes[key] = _fold(case, outcomes[key])
    return outcomes


def dimension_badges(lists: list[tuple[str, list[tuple[str, str]]]]) -> list[tuple[str, str, str, str]]:
    """``(file, label, "passed/total", color)`` per list: green when every one in it passed, red when one
    changed, orange when one was not reached, not checked or has no live test."""
    out = []
    for title, rows in lists:
        file, label = _DIMENSION_BADGES[title]
        statuses = [status for _, status, *_ in rows]
        passed = statuses.count("pass")
        color = "red" if "fail" in statuses else "green" if rows and passed == len(rows) else "orange"
        out.append((file, label, f"{passed}/{len(rows)}", color))
    return out


def _svg(left: str, right: str, color: str) -> str:
    from genbadge import Badge

    return Badge(left_txt=left, right_txt=right, color=color).as_svg(use_shields=False)


def previous_lists(page: str) -> dict[str, tuple[list[tuple[str, str, str, str]], str]]:
    """The lists of a page this script wrote before: ``{title: ([(label, status, checked, note), ...], last checked)}``.

    A list without its own "Last checked" line (a page from before there was one) takes the date in the
    page's header line, and a row without its own date (a page from before there was one) its list's."""
    header = _DATE.search(page.split("\n## ", 1)[0])
    lists: dict[str, tuple[list[tuple[str, str, str | None, str]], str]] = {}
    title = None
    for line in page.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            lists[title] = ([], header.group(0) if header else "")
        elif title and (checked := _LAST_CHECKED.match(line)):
            lists[title] = (lists[title][0], checked.group(1))
        elif title and (row := _ROW.match(line)) and row.group(2) in _STATUS_OF:
            lists[title][0].append((row.group(1), _STATUS_OF[row.group(2)], row.group(3), row.group(4) or ""))
    return {t: ([(label, status, checked if checked is not None else date, note) for label, status, checked, note in rows],
                date)
            for t, (rows, date) in lists.items()}


def _unreached_note(before: tuple[str, str, str] | None) -> str:
    """The note of a row not reached this run, from its row on the previous page (status, checked, note)."""
    runs, last = 1, None
    if before:
        status, checked, note = before
        if status == "unreached" and (streak := _STREAK.match(note)):
            runs += int(streak.group(1))
            last = (streak.group(2), streak.group(3)) if streak.group(2) else None
        elif status in ("pass", "fail"):
            last = (_SYMBOLS[status], checked)
    note = f"not reached {runs} run{'s' if runs > 1 else ''} in a row"
    return f"{note}; last {last[0]} {last[1]}" if last else note


def carry_over(lists: list[tuple[str, list[tuple[str, str]]]], previous: str, date: str
               ) -> list[tuple[str, list[tuple[str, str, str, str]], str]]:
    """Each list with its rows dated and noted, and the date it was last checked.

    A row this run checked (passed or failed) takes *date*; one not reached takes *date* and a note of how
    many runs in a row it was not reached and its last result before; one this run did not check (unknown)
    keeps its result, date and note from the *previous* page when that page had one, else stays unknown
    and undated. A list takes *date* when this run checked any of its rows, else its date on the previous
    page."""
    before = previous_lists(previous)
    out = []
    for title, rows in lists:
        kept_rows, kept_date = before.get(title, ([], ""))
        kept = {label: (status, checked, note) for label, status, checked, note in kept_rows
                if status in ("pass", "fail", "unreached")}
        dated = []
        for label, status in rows:
            if status == "unreached":
                dated.append((label, status, date, _unreached_note(kept.get(label))))
            elif status == "unknown":
                dated.append((label, *kept.get(label, ("unknown", "", ""))))
            else:
                dated.append((label, status, date, ""))
        tested = any(status != "unknown" for _, status in rows)
        out.append((title, dated, date if tested else kept_date))
    return out


def long_unreached(lists: list[tuple[str, list[tuple[str, str, str, str]], str]], runs: int = UNREACHED_RUNS
                   ) -> list[tuple[str, str, str]]:
    """``(list title, label, note)`` of each row not reached for *runs* runs in a row or more."""
    return [(title, label, note) for title, rows, _ in lists for label, status, _, note in rows
            if status == "unreached" and (streak := _STREAK.match(note)) and int(streak.group(1)) >= runs]


def render(lists: list[tuple[str, list[tuple[str, str]]]] | list[tuple[str, list[tuple[str, str]], str]],
           run_url: str | None, date: str) -> str:
    run = f"Last [workflow run]({run_url}): {date}." if run_url else f"No workflow run yet ({date})."
    lines = [
        "# Live smoke tests",
        "",
        f"{run} Generated by `scripts/smoke_report.py`; do not edit by hand.",
        "",
        "✅ passed · ❌ changed · ⛔ not reached · ❓ not checked yet · ➖ no live test",
        "",
        "Each list is checked on its own: a site's test reads that site, the matcher's scores the golden postings with the real model and checks each score falls in its "
        "hand-labelled band. Changed means the site answered but no longer as the scraper reads it; not "
        "reached means it refused the request or could not be reached (some sites refuse GitHub's runners: a "
        "local run reaches them), and its note says for how many runs and what it last was. A row a run did "
        "not check keeps its last result, with the date it was checked: CI has no Claude plan, so the "
        "matcher's comes from a local run.",
    ]
    for title, rows, *checked in lists:
        lines += ["", f"## {title}", ""]
        if checked and checked[0]:
            lines += [f"Last checked: {checked[0]}.", ""]
        lines += ["| Name | Status | Checked | Note |", "|------|--------|---------|------|",
                  *(f"| {label} | {_SYMBOLS[status]} | {checked} | {note} |" for label, status, checked, note in
                    ((*row, "", "")[:4] for row in rows))]
    return "\n".join([*lines, ""])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("junit")
    parser.add_argument("out")
    parser.add_argument("--badges", help="also write one badge SVG per list into this folder")
    parser.add_argument("--run-url")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    parser.add_argument("--unreached", help=f"write the rows not reached for {UNREACHED_RUNS} runs in a row here (empty: none)")
    args = parser.parse_args(argv)

    junit = pathlib.Path(args.junit)
    # No report means pytest never ran (e.g. setup failed): nothing is known.
    xml = junit.read_text(encoding="utf-8") if junit.exists() else "<testsuites/>"
    out = pathlib.Path(args.out)
    previous = out.read_text(encoding="utf-8") if out.exists() else ""
    lists = carry_over(sections(xml), previous, args.date)
    page = render(lists, args.run_url, args.date)
    # A local run (no --run-url) keeps the page's link to the last workflow run.
    last_run = _LAST_RUN.search(previous)
    if not args.run_url and last_run:
        page = _NO_RUN.sub(last_run.group(0), page, count=1)
    out.write_text(page, encoding="utf-8")
    if args.unreached:
        flagged = long_unreached(lists)
        pathlib.Path(args.unreached).write_text(
            "".join(f"- **{title}**: {label} ({note})\n" for title, label, note in flagged), encoding="utf-8")
    if args.badges:
        for file, label, value, color in dimension_badges([(title, rows) for title, rows, _ in lists]):
            (pathlib.Path(args.badges) / file).write_text(_svg(label, value, color), encoding="utf-8")


if __name__ == "__main__":
    main()
