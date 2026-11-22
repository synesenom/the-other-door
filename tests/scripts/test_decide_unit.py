"""Unit tests for scripts/decide.py: whether a PR's head has everything the verifier needs to pass it."""

import importlib.util
import json

import pytest

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("decide", REPO_ROOT / "scripts" / "decide.py")
decide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decide)


def _check(name, status="completed", conclusion="success", sha="H"):
    return {"name": name, "status": status, "conclusion": conclusion, "head_sha": sha}


def _decide(checks=None, body="- [x] done"):
    return decide.decide(checks if checks is not None else [_check("tests")], body, head="H")


def test_green_current_checks_and_ticked_boxes_are_ok():
    assert _decide() == (True, [])


def test_a_check_from_an_older_head_is_not_ok():
    ok, reasons = _decide([_check("tests", sha="OLD")])
    assert not ok and any("tests" in r and "older head" in r for r in reasons)


def test_an_unticked_box_is_not_ok():
    ok, reasons = _decide(body="- [ ] x")
    assert not ok and "unticked box" in reasons


def test_a_text_edited_after_the_checks_finished_is_not_ok():
    # the verifier starts only once the checks finished, so an edit after that may be the verifier ticking its own box
    checks = [_check("tests") | {"completed_at": "2026-11-21T13:39:41Z"}]
    ok, reasons = decide.decide(checks, "- [x] done", head="H", edited=[("the PR text", "2026-11-21T13:41:27Z")])
    assert not ok and "the PR text changed after the checks finished: run them again" in reasons
    assert decide.decide(checks, "- [x] done", head="H", edited=[("the PR text", "2026-11-21T13:30:00Z"),
                                                                       ("issue #3", None)]) == (True, [])


def test_a_skipped_check_does_not_hold_an_edit_made_while_the_others_ran():
    # PR #507: the skipped dependabot job finished at once, 8 s before the description was edited
    checks = [_check("merge", conclusion="skipped") | {"completed_at": "2026-11-21T18:23:52Z"},
              _check("tests") | {"completed_at": "2026-11-21T18:27:33Z"}]
    assert decide.decide(checks, "- [x] done", head="H",
                         edited=[("the PR text", "2026-11-21T18:24:00Z")]) == (True, [])


def test_rerunning_one_check_does_not_lift_the_hold():
    # every check must have finished after the edit, so rerunning the cheapest one is not enough
    checks = [_check("tests") | {"completed_at": "2026-11-21T13:39:41Z"},
              _check("merge") | {"completed_at": "2026-11-21T13:50:00Z"}]
    ok, reasons = decide.decide(checks, "- [x] done", head="H", edited=[("the PR text", "2026-11-21T13:41:27Z")])
    assert not ok and "the PR text changed after the checks finished: run them again" in reasons


def test_an_unticked_box_inside_a_fence_is_ignored():
    assert _decide(body="```\n- [ ] x\n```\n- [x] y") == (True, [])


def test_a_needs_the_maintainer_line_is_not_ok():
    ok, reasons = _decide(body="- [x] a\nNeeds the maintainer: pick a colour")
    assert not ok and "Needs the maintainer: pick a colour" in reasons


@pytest.mark.parametrize("status", ["in_progress", "queued"])
def test_a_pending_check_is_not_ok(status):
    ok, reasons = _decide([_check("tests", status=status, conclusion=None)])
    assert not ok and any("tests" in r and "pending" in r for r in reasons)


def test_a_failed_check_is_not_ok():
    ok, reasons = _decide([_check("tests", conclusion="failure")])
    assert not ok and any("tests" in r and "failed" in r for r in reasons)


def test_skipped_and_neutral_checks_are_green():
    assert _decide([_check("a", conclusion="skipped"), _check("b", conclusion="neutral")]) == (True, [])


def test_no_checks_is_not_ok():
    ok, reasons = _decide([])
    assert not ok and "no checks yet" in reasons


ISSUE = "Running prepare twice keeps one folder."


def _run(checks, body="Prepare twice keeps one folder.\n- [x] done", files=("src/door/x.py",), author="synesenom", issues=None,
         edited=None):
    issues = issues or {}
    edited = edited or {}
    calls = []

    def run(args):
        calls.append(args)
        if args[:2] == ["api", "graphql"]:
            pr = {"lastEditedAt": edited.get("pr"), "closingIssuesReferences": {
                "nodes": [{"number": n, "lastEditedAt": edited.get(n)} for n in issues]}}
            return {"data": {"repository": {"pullRequest": pr}}}
        if args[:2] == ["pr", "view"]:
            return {"number": 7, "headRefOid": "H", "body": body, "author": {"login": author},
                    "closingIssuesReferences": [{"number": n} for n in issues]}
        if args[:2] == ["issue", "view"]:
            return {"body": ISSUE, "author": {"login": issues[int(args[2])]}}
        assert "--slurp" in args  # --paginate alone concatenates the pages' objects
        if "/files" in args[-1]:
            return [[{"filename": f} for f in files[:100]], [{"filename": f} for f in files[100:]]]
        return [{"check_runs": checks[:1]}, {"check_runs": checks[1:]}]

    return run, calls


def _main7(tmp_path, run, extra=()):
    f = tmp_path / "checks.json"
    f.write_text(json.dumps([_c("twice keeps one folder"), *extra]))
    return decide.main(["7", "--checks", str(f)], run)


SHOT = {"goal": decide.SCREENS, "saw": "the card with two buttons, light, dark and 390 px", "matches_goal": True, "ran": True}


@pytest.mark.parametrize(
    "path", ["app/src/renderer/a.tsx", "app/src/web/a.ts", "app/src/preview/a.tsx", "docs/design/README.md"]
)
def test_a_screen_change_without_the_screens_check_fails_back_to_claude(tmp_path, capsys, path):
    run, _ = _run([_check("tests")], files=[path])
    assert _main7(tmp_path, run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "failure" and out["description"] == f"FAIL: not checked: {decide.SCREENS}"


def test_a_screen_change_whose_screens_passed_the_verifier_merges(tmp_path, capsys):
    run, _ = _run([_check("tests")], files=["app/src/renderer/a.tsx"])
    assert _main7(tmp_path, run, [SHOT]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "success"


def test_a_design_rule_broken_fails_a_screen_change_with_no_goal_about_screens(tmp_path, capsys):
    run, _ = _run([_check("tests")], files=["app/src/renderer/a.tsx"])
    broken = SHOT | {"saw": "two primary buttons in one view", "matches_goal": False}
    assert _main7(tmp_path, run, [broken]) == 1
    assert json.loads(capsys.readouterr().out)["description"] == f"FAIL: {decide.SCREENS}"


def test_screens_not_shot_is_a_failure_not_run(tmp_path, capsys):
    run, _ = _run([_check("tests")], files=["app/src/renderer/a.tsx"])
    assert _main7(tmp_path, run, [SHOT | {"ran": False}]) == 1
    assert json.loads(capsys.readouterr().out)["description"] == f"FAIL: not run: {decide.SCREENS}"


def test_main_reads_every_changed_file_past_the_first_hundred(tmp_path, capsys):
    run, _ = _run([_check("tests")], files=[f"src/door/f{i}.py" for i in range(150)] + ["app/src/web/x.ts"])
    assert _main7(tmp_path, run) == 1
    assert json.loads(capsys.readouterr().out)["description"] == f"FAIL: not checked: {decide.SCREENS}"


def test_main_reports_ok_and_drops_the_verify_check(tmp_path, capsys):
    run, calls = _run([_check("tests"), _check("verify", status="in_progress", conclusion=None)])
    assert _main7(tmp_path, run) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"state": "success", "description": "PASS", "reasons": [], "sha": "H"}
    assert calls[0][:3] == ["pr", "view", "7"]
    assert any("commits/H/check-runs" in " ".join(c) for c in calls)


def test_main_holds_a_pr_whose_text_or_issue_changed_after_the_checks(tmp_path, capsys):
    done = {"completed_at": "2026-11-21T13:39:41Z"}
    run, _ = _run([_check("tests") | done], issues={3: "synesenom"}, edited={"pr": "2026-11-21T13:41:27Z",
                                                                             3: "2026-11-21T13:40:00Z"})
    assert _main7(tmp_path, run) == 1
    reasons = json.loads(capsys.readouterr().out)["reasons"]
    assert reasons == ["the PR text changed after the checks finished: run them again",
                       "issue #3 changed after the checks finished: run them again"]


def test_main_reads_every_page_of_check_runs(tmp_path, capsys):
    run, _ = _run([_check("tests"), _check("app", conclusion="failure")])
    assert _main7(tmp_path, run) == 1
    assert "check app failed" in json.loads(capsys.readouterr().out)["reasons"]


@pytest.mark.parametrize("line", ["+ [ ] x", "1. [ ] x", "  * [ ] x"])
def test_every_task_list_marker_counts_as_a_box(line):
    assert "unticked box" in _decide(body=line)[1]


def test_a_tilde_fence_hides_its_boxes():
    assert _decide(body="~~~\n- [ ] x\n~~~") == (True, [])


@pytest.mark.parametrize("line", ["- Needs the maintainer: try it", "**Needs the maintainer:** try it"])
def test_a_needs_the_maintainer_line_in_a_list_or_in_bold_is_seen(line):
    assert _decide(body=line) == (False, ["Needs the maintainer: try it"])


def test_main_says_when_gh_fails(tmp_path, capsys):
    def run(args):
        raise decide.subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 404")

    assert _main7(tmp_path, run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "pending" and "gh failed" in out["reasons"][0]


def test_main_says_when_the_edit_times_cannot_be_read(tmp_path, capsys):
    good, _ = _run([_check("tests")])

    def run(args):
        if args[:2] == ["api", "graphql"]:
            raise decide.subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 502")
        return good(args)

    assert _main7(tmp_path, run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "pending" and "gh failed" in out["reasons"][0]


def test_main_takes_the_pr_by_its_url(tmp_path, capsys):
    run, calls = _run([_check("tests")])
    f = tmp_path / "checks.json"
    f.write_text(json.dumps([_c("twice keeps one folder")]))
    assert decide.main(["https://github.com/synesenom/the-other-door/pull/7", "--checks", str(f)], run) == 0
    assert any("pullRequest(number:7)" in " ".join(c) for c in calls)


def test_main_without_checks_is_a_usage_error(capsys):
    assert decide.main(["7"], lambda args: None) == 2
    assert capsys.readouterr().out == ""


# --open: the session-start list of the user's open PRs that need something
_OK = [{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]


def _pr(n=1, base="main", mergeable="MERGEABLE", rollup=_OK, body=""):
    return {"number": n, "baseRefName": base, "mergeable": mergeable, "statusCheckRollup": rollup, "body": body}


def _verify(state, description=""):
    return {"context": "verify", "state": state, "description": description}


@pytest.mark.parametrize(
    "pr, lines",
    [
        (_pr(), []),
        (_pr(base="epic/478-x", mergeable="CONFLICTING"), ["#1 conflicts with epic/478-x"]),
        (_pr(rollup=[{"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"}]), ["#1: tests failed"]),
        (_pr(rollup=[{"name": "app", "status": "IN_PROGRESS", "conclusion": None}]), []),
        (_pr(rollup=[]), ["#1: no checks ran"]),
        (_pr(rollup=_OK + [_verify("FAILURE", "FAIL: x")]), ["#1: verify failed: FAIL: x"]),
        (_pr(rollup=_OK + [_verify("PENDING", "Needs the maintainer: look at it")]), ["#1: verify pending: Needs the maintainer: look at it"]),
        (_pr(rollup=_OK + [_verify("SUCCESS", "PASS")]), ["#1: verified, not merged"]),
        (_pr(body="- Needs the maintainer: try it\r\n"), ["#1: needs the maintainer: try it"]),
        (_pr(body="~~~\n```\nNeeds the maintainer: quoted\n~~~\n"), []),
    ],
)
def test_attention_names_what_an_open_pr_needs(pr, lines):
    assert decide.attention(pr) == lines


def test_attention_reads_the_body_only_while_verify_has_not_spoken():
    pr = _pr(rollup=_OK + [_verify("PENDING", "check app is pending")], body="Needs the maintainer: try it")
    assert decide.attention(pr) == ["#1: verify pending: check app is pending"]


def test_open_prints_a_heading_and_the_lines(capsys):
    prs = [_pr(1), _pr(2, rollup=[])]
    assert decide.main(["--open"], lambda args: prs) == 0
    assert capsys.readouterr().out == "Open PRs that need you:\n#2: no checks ran\n"


def test_open_is_silent_when_gh_fails_or_nothing_needs_you(capsys):
    def fail(args):
        raise decide.subprocess.TimeoutExpired(["gh"], 5)

    assert decide.main(["--open"], fail) == 0
    assert decide.main(["--open"], lambda args: [_pr()]) == 0
    assert capsys.readouterr().out == ""


# the verdict is computed from the checks, not written by the verifier
def _v(checks, gate_ok, reasons):
    """verdict() with an issue that quotes every goal, for the cases that are not about grounding."""
    return decide.verdict(checks, gate_ok, reasons, " ".join(c["goal"] for c in checks))


def _c(goal="keeps one folder", ran=True, ok=True):
    return {"goal": goal, "saw": "x", "matches_goal": ok, "ran": ran}


def test_a_ran_check_that_misses_its_goal_is_a_failure():
    assert _v([_c(ok=False)], True, []) == ("failure", "FAIL: keeps one folder")


def test_checks_that_all_match_defer_to_the_gate():
    assert _v([_c()], True, []) == ("success", "PASS")
    assert _v([_c()], False, ["unticked box", "check a failed"]) == (
        "pending", "unticked box; check a failed")


def test_a_failure_outranks_a_check_not_run():
    state, desc = _v([_c("one two three", ran=False), _c("b b b", ok=False)], True, [])
    assert (state, desc) == ("failure", "FAIL: b b b")


def test_a_check_not_run_is_a_failure():
    assert _v([_c(), _c("two two two", ran=False)], True, []) == ("failure", "FAIL: not run: two two two")


def test_no_checks_is_pending():
    assert _v([], True, []) == ("pending", "no checks")


def test_a_goal_that_is_not_the_issues_text_is_pending():
    state, desc = decide.verdict([_c("one folder only", ok=False)], True, [], issue=ISSUE)
    assert state == "pending" and desc.startswith("goal words not in the issue: one folder only")


def test_a_goal_found_in_the_issue_counts_whatever_the_whitespace():
    assert decide.verdict([_c("twice  keeps\none folder")], True, [], issue=ISSUE) == ("success", "PASS")


@pytest.mark.parametrize("goal", ["", "one", "two words"])
def test_a_goal_under_three_words_is_ungrounded(goal):
    state, desc = decide.verdict([_c(goal)], True, [], issue="one two words here " + goal)
    assert state == "pending" and desc.startswith("goal words not in the issue")


@pytest.mark.parametrize("ran", ["false", "true", 1, None])
def test_only_a_true_bool_counts_as_run(ran):
    check = _c() | {"ran": ran}
    assert _v([check], True, []) == ("failure", "FAIL: not run: keeps one folder")


def test_a_matches_goal_that_is_not_a_bool_is_not_run():
    check = _c() | {"matches_goal": "false"}
    assert _v([check], True, []) == ("failure", "FAIL: not run: keeps one folder")


def _checks_file(tmp_path, checks):
    f = tmp_path / "checks.json"
    f.write_text(json.dumps(checks))
    return str(f)


def test_main_with_checks_prints_the_verdict(tmp_path, capsys):
    run, _ = _run([_check("tests")], issues={5: "synesenom"})
    f = _checks_file(tmp_path, [_c("twice keeps one folder", ok=False)])
    assert decide.main(["7", "--checks", f], run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out == {"state": "failure", "description": "FAIL: twice keeps one folder",
                   "reasons": [], "sha": "H"}


def test_main_with_checks_defers_to_the_gate_and_cuts_the_description(tmp_path, capsys):
    run, _ = _run([_check("tests", conclusion="failure")])
    f = _checks_file(tmp_path, [_c("keeps one folder")])
    decide.main(["7", "--checks", f], run)
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "pending" and out["reasons"] == ["check tests failed"]
    long = _checks_file(tmp_path, [_c("keeps one folder", ran=False)] * 1)
    run, _ = _run([_check("tests")])
    decide.main(["7", "--checks", long], run)
    assert len(json.loads(capsys.readouterr().out)["description"]) <= 140


def test_offline_checks_read_the_issue_from_a_file_and_call_no_gh(tmp_path, capsys):
    issue = tmp_path / "issue.md"
    issue.write_text(ISSUE)
    f = _checks_file(tmp_path, [_c("keeps one folder")])

    def no_gh(args):
        raise AssertionError("gh called")

    assert decide.main(["--checks", f, "--issue", str(issue)], no_gh) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "success" and out["sha"] is None


# the author guard
def test_a_pr_by_someone_else_needs_the_maintainer():
    ok, reasons = decide.decide([_check("tests")], "- [x] a", head="H", author="mallory")
    assert not ok and reasons == ["Needs the maintainer: opened by mallory"]


def test_an_issue_opened_by_someone_else_needs_the_maintainer():
    ok, reasons = decide.decide([_check("tests")], "- [x] a", head="H", issues=[(5, "mallory")])
    assert not ok and reasons == ["Needs the maintainer: issue #5 opened by mallory"]


def test_the_owner_as_author_of_pr_and_issue_passes():
    assert decide.decide([_check("tests")], "- [x] a", head="H", author="synesenom",
                         issues=[(5, "synesenom")]) == (True, [])


def test_main_reads_the_author_and_the_closing_issues_authors(tmp_path, capsys):
    run, _ = _run([_check("tests")], author="mallory", issues={5: "eve"})
    assert _main7(tmp_path, run) == 1
    reasons = json.loads(capsys.readouterr().out)["reasons"]
    assert "Needs the maintainer: opened by mallory" in reasons
    assert "Needs the maintainer: issue #5 opened by eve" in reasons


def test_with_no_closing_issue_the_goal_is_grounded_in_the_pr_body(tmp_path, capsys):
    run, _ = _run([_check("tests")], body="Prepare twice keeps one folder.\n- [x] ok")
    f = _checks_file(tmp_path, [_c("twice keeps one folder")])
    assert decide.main(["7", "--checks", f], run) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "success"


def test_a_closing_issue_grounds_the_goals_and_the_pr_body_box_is_the_gates(tmp_path, capsys):
    run, _ = _run([_check("tests")], body="- [ ] x", issues={5: "synesenom"})
    f = _checks_file(tmp_path, [_c("twice keeps one folder")])
    assert decide.main(["7", "--checks", f], run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "pending" and out["description"] == "unticked box"


def test_a_long_description_is_cut_to_140(tmp_path, capsys):
    run, _ = _run([_check("tests")], body="- [ ] x\nNeeds the maintainer: " + "x" * 300, issues={5: "synesenom"})
    f = _checks_file(tmp_path, [_c("twice keeps one folder")])
    decide.main(["7", "--checks", f], run)
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "pending" and len(out["description"]) == 140


def test_gh_failing_under_checks_prints_a_pending_verdict(tmp_path, capsys):
    def run(args):
        raise decide.subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 404 " + "y" * 300)

    f = _checks_file(tmp_path, [_c()])
    assert decide.main(["7", "--checks", f], run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "pending" and out["sha"] is None
    assert out["description"].startswith("gh failed: HTTP 404") and len(out["description"]) == 140
    assert out["reasons"][0].startswith("gh failed")


@pytest.mark.parametrize("content", [
    json.dumps({"goal": "a b c"}),
    json.dumps([{"goal": "a b c", "saw": "x", "matches_goal": True}]),
    json.dumps([{"goal": "a b c", "ran": True, "matches_goal": True}]),
    json.dumps(["text"]),
    "not json",
])
def test_a_bad_checks_file_is_pending(tmp_path, capsys, content):
    f = tmp_path / "c.json"
    f.write_text(content)
    run, _ = _run([_check("tests")])
    assert decide.main(["7", "--checks", str(f)], run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "pending" and out["description"] == "bad checks file"


def _trust_run(author, subs=(), fail=False):
    calls = []

    def run(args):
        calls.append(args)
        if fail:
            raise decide.subprocess.CalledProcessError(1, args, stderr="HTTP 404")
        if args[-1].startswith("repos/") and "sub_issues" not in args[-1]:
            return {"number": 9, "user": {"login": author}}
        return [[{"number": n, "user": {"login": who}} for n, who in subs]]

    return run, calls


def test_trusted_passes_the_owners_issue_and_names_strangers_sub_issues(capsys):
    run, calls = _trust_run("synesenom", subs=[(10, "synesenom"), (11, "mallory")])
    assert decide.main(["--trusted", "9"], run) == 0
    assert json.loads(capsys.readouterr().out) == {"trusted": True, "author": "synesenom", "strangers": [11]}
    assert calls[0] == ["api", "repos/synesenom/the-other-door/issues/9"]


def test_trusted_refuses_a_strangers_issue(capsys):
    run, _ = _trust_run("mallory")
    assert decide.main(["--trusted", "9"], run) == 1
    assert json.loads(capsys.readouterr().out)["trusted"] is False


def test_trusted_refuses_when_gh_fails(capsys):
    run, _ = _trust_run("synesenom", fail=True)
    assert decide.main(["--trusted", "9"], run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["trusted"] is False and "HTTP 404" in out["error"]


def test_trusted_reads_no_sub_issues_for_a_pr(capsys):
    calls = []

    def run(args):
        calls.append(args)
        return {"number": 9, "user": {"login": "synesenom"}, "pull_request": {}}

    assert decide.main(["--trusted", "9"], run) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("err", [OSError("no gh"), ValueError("bad json"), decide.subprocess.TimeoutExpired("gh", 30)])
def test_trusted_refuses_with_json_when_gh_is_missing_or_stalls(capsys, err):
    def run(args):
        raise err

    assert decide.main(["--trusted", "9"], run) == 1
    assert json.loads(capsys.readouterr().out)["trusted"] is False


EPIC = """Goal.

**Done when**
1. A PR merges by itself when every check is green.
2. Run on a past PR, each reviewer quotes a command.

**Notes** after."""


def test_a_done_when_item_with_no_check_is_a_failure():
    state, why = decide.verdict([_c("merges by itself when every check")], True, [], EPIC)
    assert state == "failure" and why.startswith("FAIL: not checked: Run on a past PR")


def test_every_done_when_item_checked_passes():
    checks = [_c("merges by itself when every check"), _c("each reviewer quotes a command")]
    assert decide.verdict(checks, True, [], EPIC) == ("success", "PASS")


def test_an_inline_done_when_must_be_checked_too():
    text = "Body.\n\nDone when: the go rule holds, and the run is green."
    assert decide.verdict([_c("the go rule holds")], True, [], text)[0] == "success"
    assert decide.verdict([_c("Body. Done when:")], True, [], text)[0] == "failure"


def test_an_issue_with_no_done_when_needs_only_its_checks():
    assert decide.verdict([_c("keeps one folder")], True, [], "It keeps one folder.") == ("success", "PASS")


def test_each_sentence_of_an_item_needs_its_own_check():
    text = "**Done when**\n1. Run on a past PR, each reviewer quotes a command. Rerunning it shows the same thing."
    assert decide.verdict([_c("Rerunning it shows the same thing")], True, [], text)[0] == "failure"
    both = [_c("Rerunning it shows the same thing"), _c("each reviewer quotes a command")]
    assert decide.verdict(both, True, [], text)[0] == "success"


def test_a_sentence_that_needs_the_merge_is_not_asked_before_it():
    text = "Done when: the go rule holds, and this PR was merged by auto-merge."
    assert decide.verdict([_c("the go rule holds")], True, [], text)[0] == "success"


def test_a_pointer_to_another_done_when_item_asks_for_that_item():
    epic = "**Done when**\n1. One thing works here.\n2. Each reviewer quotes a command.\n"
    sub = "\nDone when: Done-when 2 holds."
    assert decide.verdict([_c("One thing works here")], True, [], epic + sub)[0] == "failure"
    checks = [_c("One thing works here"), _c("Each reviewer quotes a command")]
    assert decide.verdict(checks, True, [], epic + sub)[0] == "success"
    assert decide.verdict([_c("Done-when 2 holds")], True, [], sub)[0] == "failure"


@pytest.mark.parametrize("text", [
    "## Done when\n\n1. alpha beta gamma.\n2. delta epsilon zeta.\n",
    "**Done when** (all hold):\n1. alpha beta gamma.\n2. delta epsilon\n   zeta.\n",
    "Done when:\n\n- alpha beta gamma.\n\n- delta epsilon zeta.\n\nAfter.",
    "Done when:\n+ alpha beta gamma.\n+ delta epsilon zeta.\n",
])
def test_done_when_reads_every_markdown_shape(text):
    assert [" ".join(i.split()) for i in decide.done_when(text)] == ["alpha beta gamma.", "delta epsilon zeta."]


def test_done_when_ignores_a_fenced_block():
    assert decide.done_when("Text.\n```\nDone when: alpha beta gamma.\n```\n") == []


def test_a_goal_marked_for_the_maintainer_waits_for_them_and_needs_no_check():
    text = "**Done when**\n1. One thing works here.\n2. The installer opens on a clean Mac (by the maintainer).\n"
    state, why = decide.verdict([_c("One thing works here")], True, [], text)
    assert state == "pending" and why.startswith("Needs the maintainer: The installer opens")


MINE = "**Done when**\n1. One thing works here.\n2. The installer opens on a clean Mac (by the maintainer).\n"


def test_a_check_written_for_the_maintainers_goal_need_not_run():
    checks = [_c("One thing works here"), _c("installer opens on a clean", ran=False)]
    assert decide.verdict(checks, True, [], MINE)[0] == "pending"


@pytest.mark.parametrize("text", [
    "**Done when**\n1. One thing works here.\n2. The installer opens on a clean Mac. (by the maintainer)\n",
    "Done when: One thing works here. The installer opens on a clean Mac (by the maintainer).",
])
def test_the_maintainer_mark_works_inline_and_after_the_full_stop(text):
    state, why = decide.verdict([_c("One thing works here")], True, [], text)
    assert state == "pending" and "installer opens" in why


def test_an_untested_goal_beats_the_maintainers_wait():
    assert decide.verdict([_c("installer opens on a clean")], True, [], MINE)[0] == "failure"


def test_only_the_maintainers_goals_need_no_checks():
    text = "Done when: The installer opens on a clean Mac (by the maintainer)."
    assert decide.verdict([], True, [], text)[1].startswith("Needs the maintainer")


def test_the_maintainers_wait_comes_before_the_gate():
    assert decide.verdict([_c("One thing works here")], False, ["check test failed"], MINE)[1].startswith("Needs the maintainer")
