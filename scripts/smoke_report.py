"""Turn the live smoke run's JUnit XML into a status page, one list per dimension.

The live-smoke workflow runs ``./scripts/run-test.sh --live --junitxml=...``
and then this script, which writes docs/badges/live-smoke.md. Each dimension is checked on its own,
so each has its own list:

- **Boards:** the boards (``Site.board``);
- **Employer feeds:** the other sites (``Site.config_key``);
- **Countries:** every ``i18n/country/`` file, from ``tests/i18n/test_countries_live.py``'s ``[<cc>]`` runs;
- **Languages:** every ``i18n/lang/`` file, from ``tests/i18n/test_languages_live.py``'s ``[<code>]`` runs;
- **Matcher:** every golden scoring case (``tests/matching/fixtures/golden/``), from
  ``tests/matching/test_matcher_golden.py``'s ``[<case>]`` runs (the real scorer on a Claude plan).

Each row is ✅ (its smoke tests passed), ❌ (one failed or errored), ❓ (not run in CI, or skipped)
or ➖ (it has no live test; ``tests/live_matrix.NO_LIVE_TEST`` says why).

A list that nothing in this run tested (every row ❓) keeps its rows from the page already at <out.md>,
with the date it was last checked: CI has no Claude plan and skips the golden set, so the weekly run
keeps the matcher's last local result, and a local run of the golden set alone keeps the sites' last
CI result.

With ``--badges DIR`` it also writes one badge per list into DIR (``live-boards.svg``,
``live-feeds.svg``, ``live-countries.svg``, ``live-languages.svg``, ``live-matcher.svg``): "boards | 3/3", how
many passed of how many, green only when every one passed and red when even one failed, was not run or has
no live test. The badges are committed SVGs rather than GitHub's workflow badge URL, which can only say whether the
whole run passed.

Usage:  python scripts/smoke_report.py <junit.xml> <out.md> [--badges DIR] [--run-url URL] [--date YYYY-MM-DD]
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
_SYMBOLS = {"pass": "✅", "fail": "❌", "unknown": "❓", "none": "➖"}
_STATUS_OF = {symbol: status for status, symbol in _SYMBOLS.items()}
_ROW = re.compile(r"^\| (.+) \| (\S+) \|$")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LAST_CHECKED = re.compile(r"^Last checked: (\d{4}-\d{2}-\d{2})\.$")
# Each list's badge: (its file, its label), by the list's title on the page.
_DIMENSION_BADGES = {
    "Boards": ("live-boards.svg", "boards"),
    "Employer feeds": ("live-feeds.svg", "employer feeds"),
    "Countries": ("live-countries.svg", "countries"),
    "Languages": ("live-languages.svg", "languages"),
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
    from door import i18n
    from door.core.sites import SITES

    boards = [n for n, s in SITES.items() if s.board]
    feeds = [n for n, s in SITES.items() if not s.board]

    def site_rows(names: list[str]) -> list[tuple[str, str]]:
        outcomes = site_outcomes(xml, names)
        return [(n, outcomes[n] if _has_live_test(n) else "none") for n in names]

    countries = i18n.countries()
    by_country = param_outcomes(xml, "test_countries_live", sorted(countries))
    languages = i18n.languages()
    by_language = param_outcomes(xml, "test_languages_live", sorted(languages))
    golden = golden_case_ids()
    by_case = param_outcomes(xml, "test_matcher_golden", golden)
    return [
        ("Boards", site_rows(boards)),
        ("Employer feeds", site_rows(feeds)),
        ("Countries", [(f"{countries[cc].name} ({cc})", by_country[cc]) for cc in sorted(countries)]),
        ("Languages", [(i18n.language_label(code), by_language[code]) for code in sorted(languages)]),
        ("Matcher", [(case, by_case[case]) for case in golden]),
    ]


def site_outcomes(junit_xml: str, sites: list[str]) -> dict[str, str]:
    """Map each site to "pass", "fail" or "unknown" from a pytest JUnit report.

    A site's (or discovery source's) tests live in ``tests/scrapers/<boards|discovery|feeds>/test_<site>_live.py``, matched by file name. Any failure or error
    fails the site; a site whose tests were all skipped, or that has none in
    the report, is unknown.
    """
    outcomes = {site: "unknown" for site in sites}
    for case in ET.fromstring(junit_xml).iter("testcase"):
        match = _SITE_TEST.search(case.get("classname", ""))
        if not match or match.group(1) not in outcomes:
            continue
        site = match.group(1)
        if case.find("failure") is not None or case.find("error") is not None:
            outcomes[site] = "fail"
        elif case.find("skipped") is None and outcomes[site] == "unknown":
            outcomes[site] = "pass"
    return outcomes


def param_outcomes(junit_xml: str, module: str, keys: list[str]) -> dict[str, str]:
    """Map each key to "pass", "fail" or "unknown" from the runs of *module*'s parametrised test,
    whose parameter is the key (``test_country_live[dk]``)."""
    outcomes = {key: "unknown" for key in keys}
    for case in ET.fromstring(junit_xml).iter("testcase"):
        classname = case.get("classname", "")
        match = _PARAM_TEST.search(case.get("name", ""))
        if not (classname == module or classname.endswith("." + module)) or not match or match.group(1) not in outcomes:
            continue
        key = match.group(1)
        if case.find("failure") is not None or case.find("error") is not None:
            outcomes[key] = "fail"
        elif case.find("skipped") is None and outcomes[key] == "unknown":
            outcomes[key] = "pass"
    return outcomes


def dimension_badges(lists: list[tuple[str, list[tuple[str, str]]]]) -> list[tuple[str, str, str, str]]:
    """``(file, label, "passed/total", color)`` per list: green only when every one in it passed."""
    out = []
    for title, rows in lists:
        file, label = _DIMENSION_BADGES[title]
        passed = sum(1 for _, status in rows if status == "pass")
        out.append((file, label, f"{passed}/{len(rows)}", "green" if rows and passed == len(rows) else "red"))
    return out


def _svg(left: str, right: str, color: str) -> str:
    from genbadge import Badge

    return Badge(left_txt=left, right_txt=right, color=color).as_svg(use_shields=False)


def previous_lists(page: str) -> dict[str, tuple[list[tuple[str, str]], str]]:
    """The lists of a page this script wrote before: ``{title: (rows, last checked)}``.

    A list without its own "Last checked" line (a page from before there was one) takes the date in the
    page's header line."""
    header = _DATE.search(page.split("\n## ", 1)[0])
    lists: dict[str, tuple[list[tuple[str, str]], str]] = {}
    title = None
    for line in page.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            lists[title] = ([], header.group(0) if header else "")
        elif title and (checked := _LAST_CHECKED.match(line)):
            lists[title] = (lists[title][0], checked.group(1))
        elif title and (row := _ROW.match(line)) and row.group(2) in _STATUS_OF:
            lists[title][0].append((row.group(1), _STATUS_OF[row.group(2)]))
    return lists


def carry_over(lists: list[tuple[str, list[tuple[str, str]]]], previous: str, date: str
               ) -> list[tuple[str, list[tuple[str, str]], str]]:
    """Each list with the date it was checked: this run's, or, when nothing in it ran this time
    (every row unknown), its rows and date from the *previous* page, when that page has them."""
    before = previous_lists(previous)
    out = []
    for title, rows in lists:
        kept = before.get(title)
        untested = all(status == "unknown" for _, status in rows)
        if untested and kept and kept[0]:
            out.append((title, kept[0], kept[1]))
        else:
            out.append((title, rows, "" if untested else date))
    return out


def render(lists: list[tuple[str, list[tuple[str, str]]]] | list[tuple[str, list[tuple[str, str]], str]],
           run_url: str | None, date: str) -> str:
    run = f"Last [workflow run]({run_url}): {date}." if run_url else f"No workflow run yet ({date})."
    lines = [
        "# Live smoke tests",
        "",
        f"{run} Generated by `scripts/smoke_report.py`; do not edit by hand.",
        "",
        "✅ passed · ❌ failed · ❓ not run in CI (or skipped) · ➖ no live test",
        "",
        "Each list is checked on its own: a site's test reads that site, a country's checks its country "
        "file against real ads' places, a language's checks its language file against real ads written in it, "
        "the matcher's scores the golden postings with the real model and checks each score falls in its "
        "hand-labelled band. CI has no Claude plan and skips the matcher, so a list that a run did not test "
        "keeps its last result and date.",
    ]
    for title, rows, *checked in lists:
        lines += ["", f"## {title}", ""]
        if checked and checked[0]:
            lines += [f"Last checked: {checked[0]}.", ""]
        lines += ["| Name | Status |", "|------|--------|",
                  *(f"| {label} | {_SYMBOLS[status]} |" for label, status in rows)]
    return "\n".join([*lines, ""])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("junit")
    parser.add_argument("out")
    parser.add_argument("--badges", help="also write one badge SVG per list into this folder")
    parser.add_argument("--run-url")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)

    junit = pathlib.Path(args.junit)
    # No report means pytest never ran (e.g. setup failed): nothing is known.
    xml = junit.read_text(encoding="utf-8") if junit.exists() else "<testsuites/>"
    out = pathlib.Path(args.out)
    previous = out.read_text(encoding="utf-8") if out.exists() else ""
    lists = carry_over(sections(xml), previous, args.date)
    out.write_text(render(lists, args.run_url, args.date), encoding="utf-8")
    if args.badges:
        for file, label, value, color in dimension_badges([(title, rows) for title, rows, _ in lists]):
            (pathlib.Path(args.badges) / file).write_text(_svg(label, value, color), encoding="utf-8")


if __name__ == "__main__":
    main()
