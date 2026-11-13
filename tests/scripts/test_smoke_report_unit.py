"""Unit tests for scripts/smoke_report.py: the live smoke run's status page, one list per dimension
(boards, employer feeds, employer discovery, the matcher).

The weekly live-smoke workflow writes pytest's JUnit XML, then this script turns
it into docs/badges/live-smoke.md, the page the README's live-smoke badge links.
"""

import importlib.util
import os
import subprocess
import sys

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("smoke_report", REPO_ROOT / "scripts" / "smoke_report.py")
smoke_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke_report)


def _junit(*cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>'


def _case(module: str, name: str = "test_x", body: str = "", package: str = "tests.scrapers") -> str:
    return f'<testcase classname="{package}.{module}" name="{name}">{body}</testcase>'


def test_a_passing_live_test_marks_its_site_passed():
    xml = _junit(_case("test_greenhouse_live"))
    assert smoke_report.site_outcomes(xml, ["greenhouse"]) == {"greenhouse": "pass"}


def test_a_failure_or_error_marks_its_site_failed():
    xml = _junit(
        _case("test_lever_live", body='<failure message="boom">x</failure>'),
        _case("test_jobindex_live", body='<error message="setup">x</error>'),
    )
    assert smoke_report.site_outcomes(xml, ["lever", "jobindex"]) == {"lever": "fail", "jobindex": "fail"}


def test_one_failing_test_among_several_fails_the_site():
    xml = _junit(
        _case("test_linkedin_live", "test_a"),
        _case("test_linkedin_live", "test_b", '<failure message="boom">x</failure>'),
    )
    assert smoke_report.site_outcomes(xml, ["linkedin"]) == {"linkedin": "fail"}


def test_a_site_not_run_or_only_skipped_is_unknown():
    xml = _junit(_case("test_hellowork_live", body='<skipped message="no cookies"/>'))
    assert smoke_report.site_outcomes(xml, ["hellowork", "teamtailor"]) == {"hellowork": "unknown", "teamtailor": "unknown"}


def test_a_site_its_test_could_not_reach_is_not_reached():
    """A refusal (a 403, a 429, a wall) is not a change of the site: its own verdict, never a silent ❓."""
    xml = _junit(_case("test_reed_live", body='<skipped message="not reached: reed: 403 Forbidden"/>'),
                 _case("test_euraxess_live", body='<skipped message="no network"/>'))
    assert smoke_report.site_outcomes(xml, ["reed", "euraxess"]) == {"reed": "unreached", "euraxess": "unknown"}


def test_a_failure_beats_not_reached_and_a_pass_beats_it_too():
    xml = _junit(
        _case("test_greenhouse_live", "test_a", '<skipped message="not reached: greenhouse: 429"/>'),
        _case("test_greenhouse_live", "test_b", '<failure message="x">x</failure>'),
        _case("test_lever_live", "test_a", '<skipped message="not reached: lever: 429"/>'),
        _case("test_lever_live", "test_b"),
    )
    assert smoke_report.site_outcomes(xml, ["greenhouse", "lever"]) == {"greenhouse": "fail", "lever": "pass"}


def test_tests_that_are_not_site_smoke_tests_are_ignored():
    xml = _junit(_case("test_sync_live"), _case("test_matcher_golden", body='<failure message="x">x</failure>'))
    assert smoke_report.site_outcomes(xml, ["greenhouse"]) == {"greenhouse": "unknown"}


def test_a_parametrised_dimension_test_marks_each_of_its_keys():
    """The matcher is one parametrised test: the key is the test's parameter."""
    xml = _junit(
        _case("test_matcher_golden", "test_golden_case[a]", package="tests.matching"),
        _case("test_matcher_golden", "test_golden_case[b]", '<failure message="x">x</failure>', package="tests.matching"),
        _case("test_other", "test_golden_case[c]", '<failure message="x">x</failure>', package="tests.matching"),
    )
    assert smoke_report.param_outcomes(xml, "test_matcher_golden", ["a", "b", "c"]) == {
        "a": "pass", "b": "fail", "c": "unknown"}


def test_render_lists_every_dimension_with_its_symbols_and_the_run():
    md = smoke_report.render(
        [("Boards", [("jobindex", "pass"), ("thehub", "fail")]),
         ("Employer feeds", [("greenhouse", "none"), ("workable", "unknown")])],
        run_url="https://github.com/o/r/actions/runs/1",
        date="2026-10-12",
    )
    assert "## Boards" in md and "## Employer feeds" in md
    assert md.index("## Boards") < md.index("| jobindex | ✅ |") < md.index("## Employer feeds")
    assert "| thehub | ❌ |" in md
    assert "| greenhouse | ➖ |" in md
    assert "| workable | ❓ |" in md
    assert "2026-10-12" in md
    assert "⛔ not reached" in md and "❌ changed" in md
    assert "https://github.com/o/r/actions/runs/1" in md


def test_main_writes_the_table_and_treats_a_missing_report_as_all_unknown(tmp_path):
    out = tmp_path / "live-smoke.md"
    smoke_report.main([str(tmp_path / "missing.xml"), str(out), "--date", "2026-10-12"])
    text = out.read_text(encoding="utf-8")
    assert "| greenhouse | ❓ |" in text
    assert "| workable | ❓ |" in text


def test_main_lists_each_dimension_on_its_own(tmp_path):
    """Boards, employer feeds and the matcher are checked independently, so each has its own list: a broken
    golden case shows even when every site passes."""
    report = tmp_path / "smoke.xml"
    report.write_text(_junit(
        _case("test_jobindex_live"), _case("test_greenhouse_live"),
        _case("test_matcher_golden", "test_golden_case[domain-mismatch]", '<failure message="x">x</failure>',
              package="tests.matching"),
    ), encoding="utf-8")
    out = tmp_path / "live-smoke.md"
    smoke_report.main([str(report), str(out), "--date", "2026-10-12"])
    text = out.read_text(encoding="utf-8")
    heads = ["## Boards", "## Employer feeds", "## Employer discovery", "## Matcher"]
    assert [text.index(h) for h in heads] == sorted(text.index(h) for h in heads)

    def section(head):
        start = text.index(head)
        ends = [text.index(h) for h in heads if text.index(h) > start]
        return text[start:min(ends) if ends else len(text)]

    assert "| jobindex | ✅ |" in section("## Boards") and "| workable |" in section("## Boards")
    assert "| greenhouse | ✅ |" in section("## Employer feeds")
    assert "| domain-mismatch | ❌ |" in section("## Matcher")
    assert "## Countries" not in text and "## Languages" not in text


def test_main_reads_the_junit_report(tmp_path):
    report = tmp_path / "smoke.xml"
    report.write_text(_junit(_case("test_greenhouse_live")), encoding="utf-8")
    out = tmp_path / "live-smoke.md"
    smoke_report.main([str(report), str(out), "--date", "2026-10-12"])
    assert "| greenhouse | ✅ |" in out.read_text(encoding="utf-8")


def test_render_without_a_run_url_does_not_claim_a_workflow_run():
    md = smoke_report.render([("Employer feeds", [("greenhouse", "unknown")])], run_url=None, date="2026-10-08")
    assert "No workflow run yet" in md
    assert "Last" not in md


def test_the_live_smoke_workflow_runs_the_report_inside_poetry():
    # The script imports door.core.sites, whose package __init__ imports click:
    # bare `python` on the runner has no project deps (ModuleNotFoundError: click).
    workflow = (REPO_ROOT / ".github" / "workflows" / "live-smoke.yml").read_text(encoding="utf-8")
    assert "poetry run python scripts/smoke_report.py" in workflow


# The README's badges are committed SVGs, not GitHub's workflow badge URL: the repo is
# private, and the GitHub mobile app fetches that URL without a session (a 404).


def test_there_is_no_run_wide_badge_any_more():
    """Every badge is a list's: a run-wide "live smoke | failing" said nothing about what failed."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "live-smoke.yml").read_text(encoding="utf-8")
    assert "actions/workflows/live-smoke.yml/badge.svg" not in readme
    assert "docs/badges/live-smoke.svg" not in readme
    assert "--badge " not in workflow
    assert not (REPO_ROOT / "docs" / "badges" / "live-smoke.svg").exists()


# --- the matcher's golden set ------------------------------------------------------------------------------


def test_the_matcher_list_has_one_row_per_golden_case(tmp_path):
    report = tmp_path / "smoke.xml"
    report.write_text(_junit(
        _case("test_matcher_golden", "test_golden_case[obvious-strong-match]", package="tests.matching"),
        _case("test_matcher_golden", "test_golden_case[borderline-partial-skills]",
              '<failure message="x">x</failure>', package="tests.matching"),
    ), encoding="utf-8")
    out = tmp_path / "live-smoke.md"
    smoke_report.main([str(report), str(out), "--date", "2026-11-01"])
    matcher = out.read_text(encoding="utf-8").split("## Matcher", 1)[1]
    assert "| obvious-strong-match | ✅ |" in matcher
    assert "| borderline-partial-skills | ❌ |" in matcher
    assert "| domain-mismatch | ❓ |" in matcher  # a golden case this report did not run


def test_the_golden_case_ids_are_the_postings_ids_without_their_prefix():
    ids = smoke_report.golden_case_ids()
    assert "borderline-partial-skills" in ids and len(ids) == len(set(ids)) >= 12
    assert not any(i.startswith("golden-") for i in ids)


# --- a list nothing in this run tested keeps its last result ------------------------------------------------


def test_each_list_says_when_it_was_last_checked(tmp_path):
    report = tmp_path / "smoke.xml"
    report.write_text(_junit(_case("test_jobindex_live")), encoding="utf-8")
    out = tmp_path / "live-smoke.md"
    smoke_report.main([str(report), str(out), "--date", "2026-11-02"])
    boards = out.read_text(encoding="utf-8").split("## Boards", 1)[1].split("## ", 1)[0]
    assert "Last checked: 2026-11-02." in boards


def test_a_list_this_run_did_not_test_keeps_its_last_result_and_date(tmp_path):
    """CI has no Claude plan, so it skips the golden set: the weekly run must not wipe the matcher's
    last local result, and a local golden run must not wipe the sites' last CI result."""
    out = tmp_path / "live-smoke.md"
    local = tmp_path / "local.xml"
    local.write_text(_junit(
        _case("test_jobindex_live"),
        _case("test_matcher_golden", "test_golden_case[obvious-strong-match]", package="tests.matching"),
    ), encoding="utf-8")
    smoke_report.main([str(local), str(out), "--badges", str(tmp_path), "--date", "2026-11-01"])

    ci = tmp_path / "ci.xml"
    ci.write_text(_junit(
        _case("test_jobindex_live", body='<failure message="x">x</failure>'),
        _case("test_matcher_golden", "test_golden_case[obvious-strong-match]", '<skipped message="no claude"/>',
              package="tests.matching"),
    ), encoding="utf-8")
    smoke_report.main([str(ci), str(out), "--badges", str(tmp_path), "--date", "2026-11-02"])
    text = out.read_text(encoding="utf-8")
    matcher = text.split("## Matcher", 1)[1].split("## ", 1)[0]
    boards = text.split("## Boards", 1)[1].split("## ", 1)[0]
    assert "| obvious-strong-match | ✅ |" in matcher and "Last checked: 2026-11-01." in matcher
    assert "| jobindex | ❌ |" in boards and "Last checked: 2026-11-02." in boards
    assert "1/" in (tmp_path / "live-matcher.svg").read_text(encoding="utf-8")


def test_a_carried_list_from_an_older_page_takes_that_pages_date():
    old = "# Live smoke tests\n\nNo workflow run yet (2026-10-30). x\n\n## Boards\n\n| Name | Status |\n|------|--------|\n| jobindex | ✅ |\n"
    assert smoke_report.previous_lists(old) == {"Boards": ([("jobindex", "pass", "2026-10-30", "")], "2026-10-30")}


def test_a_site_this_run_did_not_run_keeps_its_last_result_and_its_date(tmp_path):
    """A row skipped for another reason (a test not run here) keeps the last run's result, dated."""
    out = tmp_path / "live-smoke.md"
    local = tmp_path / "local.xml"
    local.write_text(_junit(_case("test_jobindex_live"), _case("test_euraxess_live")), encoding="utf-8")
    smoke_report.main([str(local), str(out), "--badges", str(tmp_path), "--date", "2026-11-12"])

    ci = tmp_path / "ci.xml"
    ci.write_text(_junit(
        _case("test_jobindex_live"),
        _case("test_euraxess_live", body='<skipped message="not run here"/>'),
    ), encoding="utf-8")
    smoke_report.main([str(ci), str(out), "--badges", str(tmp_path), "--date", "2026-11-16"])
    boards = out.read_text(encoding="utf-8").split("## Boards", 1)[1].split("## ", 1)[0]
    assert "| jobindex | ✅ | 2026-11-16 |" in boards
    assert "| euraxess | ✅ | 2026-11-12 |" in boards
    assert "Last checked: 2026-11-16." in boards


def test_a_site_never_checked_stays_unknown(tmp_path):
    out = tmp_path / "live-smoke.md"
    ci = tmp_path / "ci.xml"
    ci.write_text(_junit(_case("test_jobindex_live")), encoding="utf-8")
    smoke_report.main([str(ci), str(out), "--date", "2026-11-16"])
    boards = out.read_text(encoding="utf-8").split("## Boards", 1)[1].split("## ", 1)[0]
    assert "| euraxess | ❓ |  |" in boards


def _not_reached(site: str) -> str:
    return _case(f"test_{site}_live", body=f'<skipped message="not reached: {site}: 403 Forbidden"/>')


def _boards(text: str) -> str:
    return text.split("## Boards", 1)[1].split("## ", 1)[0]


def test_a_site_not_reached_says_so_with_its_last_result_and_how_many_runs_in_a_row(tmp_path):
    out = tmp_path / "live-smoke.md"
    runs = [("2026-11-02", _case("test_reed_live")), ("2026-11-09", _not_reached("reed")),
            ("2026-11-16", _not_reached("reed"))]
    for date, case in runs:
        (tmp_path / "x.xml").write_text(_junit(case), encoding="utf-8")
        smoke_report.main([str(tmp_path / "x.xml"), str(out), "--date", date])
    assert "| reed | ⛔ | 2026-11-16 | not reached 2 runs in a row; last ✅ 2026-11-02 |" in _boards(out.read_text())


def test_reaching_the_site_again_ends_the_streak(tmp_path):
    out = tmp_path / "live-smoke.md"
    for date, case in [("2026-11-09", _not_reached("reed")), ("2026-11-16", _case("test_reed_live"))]:
        (tmp_path / "x.xml").write_text(_junit(case), encoding="utf-8")
        smoke_report.main([str(tmp_path / "x.xml"), str(out), "--date", date])
    assert "| reed | ✅ | 2026-11-16 |  |" in _boards(out.read_text())


def test_a_run_that_did_not_test_a_not_reached_site_keeps_its_streak(tmp_path):
    out = tmp_path / "live-smoke.md"
    for date, xml in [("2026-11-09", _junit(_not_reached("reed"))), ("2026-11-12", _junit(_case("test_jobindex_live")))]:
        (tmp_path / "x.xml").write_text(xml, encoding="utf-8")
        smoke_report.main([str(tmp_path / "x.xml"), str(out), "--date", date])
    assert "| reed | ⛔ | 2026-11-09 | not reached 1 run in a row |" in _boards(out.read_text())


def test_sites_not_reached_for_three_runs_are_written_out_for_their_own_issue(tmp_path):
    """Only a change opens the failure issue; a site not reached for weeks gets flagged on its own."""
    out, flagged = tmp_path / "live-smoke.md", tmp_path / "unreached.md"
    for date in ("2026-11-02", "2026-11-09", "2026-11-16"):
        (tmp_path / "x.xml").write_text(_junit(_not_reached("reed"), _not_reached("lever")
                                               if date != "2026-11-02" else _case("test_lever_live")), encoding="utf-8")
        smoke_report.main([str(tmp_path / "x.xml"), str(out), "--date", date, "--unreached", str(flagged)])
    text = flagged.read_text()
    assert "reed" in text and "3 runs in a row" in text and "lever" not in text


def test_nothing_long_unreached_writes_an_empty_file(tmp_path):
    flagged = tmp_path / "unreached.md"
    (tmp_path / "x.xml").write_text(_junit(_not_reached("reed")), encoding="utf-8")
    smoke_report.main([str(tmp_path / "x.xml"), str(tmp_path / "out.md"), "--date", "2026-11-16", "--unreached", str(flagged)])
    assert flagged.read_text() == ""


def test_the_script_finds_the_package_without_src_on_the_path(tmp_path):
    # The workflow runs `poetry run python scripts/smoke_report.py` with no PYTHONPATH;
    # pytest's own pythonpath would hide a broken import, so run it in a clean process.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    out = tmp_path / "live-smoke.md"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "smoke_report.py"), str(tmp_path / "none.xml"), str(out)],
        env=env, cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "| pinpoint |" in out.read_text()


# --- one badge per dimension -------------------------------------------------------------------------------

_LISTS = [
    ("Boards", [("jobindex", "pass"), ("thehub", "pass")]),
    ("Employer feeds", [("greenhouse", "pass"), ("lever", "fail")]),
    ("Matcher", [("obvious-strong-match", "pass"), ("borderline-partial-skills", "fail")]),
]


def test_each_dimension_has_a_badge_with_how_many_passed():
    """Green when every one in the list passed, red when one changed, orange when one was not reached,
    not checked or has no live test."""
    assert smoke_report.dimension_badges([*_LISTS, ("Boards", [("reed", "unreached"), ("jobindex", "pass")])]) == [
        ("live-boards.svg", "boards", "2/2", "green"),
        ("live-feeds.svg", "employer feeds", "1/2", "red"),
        ("live-matcher.svg", "matcher", "1/2", "red"),
        ("live-boards.svg", "boards", "1/2", "orange"),
    ]


def test_main_writes_the_dimension_badges_when_asked(tmp_path):
    report = tmp_path / "smoke.xml"
    report.write_text(_junit(_case("test_jobindex_live"), _case("test_thehub_live"), _case("test_euraxess_live"), _case("test_jobbank_live"), _case("test_jobmaskinen_live"), _case("test_workable_live"),
                      _case("test_globalnyt_live"), _case("test_reliefweb_live"), _case("test_arbetsformedlingen_live"), _case("test_francetravail_live"), _case("test_choisirleservicepublic_live"), _case("test_kozigallas_live"), _case("test_reed_live"), _case("test_jobs_ac_uk_live"), _case("test_nhs_jobs_live")),
                      encoding="utf-8")
    smoke_report.main([str(report), str(tmp_path / "live-smoke.md"), "--badges", str(tmp_path), "--date", "2026-10-12"])
    boards = (tmp_path / "live-boards.svg").read_text(encoding="utf-8")
    assert boards.lstrip().startswith("<svg") and "boards" in boards and "15/15" in boards
    for name in ("live-feeds.svg", "live-discovery.svg", "live-matcher.svg"):
        assert (tmp_path / name).read_text(encoding="utf-8").lstrip().startswith("<svg")


def test_the_readme_shows_the_dimension_badges_linked_to_their_lists():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for svg, anchor in (("live-boards", "boards"), ("live-feeds", "employer-feeds"),
                        ("live-discovery", "employer-discovery"), ("live-matcher", "matcher")):
        assert f"(docs/badges/{svg}.svg)](docs/badges/live-smoke.md#{anchor})" in readme


def test_the_live_smoke_workflow_writes_and_commits_the_dimension_badges():
    workflow = (REPO_ROOT / ".github" / "workflows" / "live-smoke.yml").read_text(encoding="utf-8")
    assert "--badges docs/badges" in workflow and "docs/badges/live-*.svg" in workflow


def test_a_local_run_keeps_the_link_to_the_last_workflow_run(tmp_path):
    out = tmp_path / "live-smoke.md"
    report = tmp_path / "x.xml"
    report.write_text(_junit(_case("test_jobindex_live")), encoding="utf-8")
    smoke_report.main([str(report), str(out), "--run-url", "https://example.test/runs/1", "--date", "2026-11-09"])
    smoke_report.main([str(report), str(out), "--date", "2026-11-12"])
    assert "Last [workflow run](https://example.test/runs/1): 2026-11-09." in out.read_text(encoding="utf-8")


def test_the_discovery_sources_and_wikidata_have_a_list_of_their_own_and_detect_only_platforms_are_feeds(tmp_path):
    """Discovery runs locally (#19): its sources and the Wikidata lookup are one list, kept between CI runs; a
    platform The other door only detects (HR-ON, iCIMS, ...) is a row of the employer feeds, by its detection test."""
    report = tmp_path / "smoke.xml"
    report.write_text(_junit(
        _case("test_linkedin_live", package="tests.scrapers.discovery"),
        _case("test_wikidata_live", "test_wikidata_lookup_live[x]", package="tests.core"),
        _case("test_hr_on_live", "test_hr_on_detection_live", package="tests.scrapers.feeds"),
    ), encoding="utf-8")
    out = tmp_path / "live-smoke.md"
    smoke_report.main([str(report), str(out), "--date", "2026-10-12"])
    text = out.read_text(encoding="utf-8")
    feeds, discovery = text.index("## Employer feeds"), text.index("## Employer discovery")
    assert feeds < discovery < text.index("## Matcher")
    assert "| hr_on | ✅ |" in text[feeds:discovery]
    assert "| linkedin | ✅ |" in text[discovery:] and "| wikidata | ✅ |" in text[discovery:]
    assert "| profession |" in text[discovery:]


def test_the_discovery_list_has_its_badge():
    assert smoke_report.dimension_badges([("Employer discovery", [("linkedin", "pass")])]) == [
        ("live-discovery.svg", "employer discovery", "1/1", "green")]


_FAILED = '<failure message="AssertionError: reed [details]: description: 2/2 break it">x</failure>'


def test_a_changed_row_names_the_modes_that_changed(tmp_path):
    """A broken mode fails the run with a message naming the site and the mode (#19): the row says which."""
    out = tmp_path / "live-smoke.md"
    (tmp_path / "x.xml").write_text(_junit(
        _case("test_reed_live", "test_reed_listing_live"),
        _case("test_reed_live", "test_reed_details_live", _FAILED),
        _case("test_reed_live", "test_reed_page2_live", _FAILED),
    ), encoding="utf-8")
    smoke_report.main([str(tmp_path / "x.xml"), str(out), "--date", "2026-11-16"])
    assert "| reed | ❌ | 2026-11-16 | changed: details, page2 |" in _boards(out.read_text())


def test_the_changed_rows_are_written_out_for_the_failure_issue(tmp_path):
    (tmp_path / "x.xml").write_text(_junit(
        _case("test_reed_live", "test_reed_details_live", _FAILED),
        _case("test_greenhouse_live", "test_greenhouse_detection_live", _FAILED),
        _case("test_jobindex_live", "test_jobindex_listing_live"),
    ), encoding="utf-8")
    changed = tmp_path / "changed.md"
    smoke_report.main([str(tmp_path / "x.xml"), str(tmp_path / "live-smoke.md"), "--date", "2026-11-16",
                       "--changed", str(changed)])
    assert changed.read_text() == "- **Boards**: reed (changed: details)\n- **Employer feeds**: greenhouse (changed: detection)\n"


def test_the_failure_issue_lists_the_changed_rows():
    workflow = (REPO_ROOT / ".github" / "workflows" / "live-smoke.yml").read_text(encoding="utf-8")
    assert "--changed smoke-changed.md" in workflow and "smoke-changed.md" in workflow.split("Open or update failure issue")[1]
