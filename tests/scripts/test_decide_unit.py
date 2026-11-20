"""Unit tests for scripts/decide.py: whether a PR's head has everything the verifier needs to pass it."""

import importlib.util
import json

import pytest

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("decide", REPO_ROOT / "scripts" / "decide.py")
decide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decide)

FILES = ["src/door/x.py"]


def _check(name, status="completed", conclusion="success", sha="H"):
    return {"name": name, "status": status, "conclusion": conclusion, "head_sha": sha}


def _decide(checks=None, body="- [x] done", files=FILES):
    return decide.decide(checks if checks is not None else [_check("tests")], body, files, head="H")


def test_green_current_checks_and_ticked_boxes_are_ok():
    assert _decide() == (True, [])


def test_a_check_from_an_older_head_is_not_ok():
    ok, reasons = _decide([_check("tests", sha="OLD")])
    assert not ok and any("tests" in r and "older head" in r for r in reasons)


def test_an_unticked_box_is_not_ok():
    ok, reasons = _decide(body="- [ ] x")
    assert not ok and "unticked box" in reasons


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


@pytest.mark.parametrize(
    "path", ["app/src/renderer/a.tsx", "app/src/web/a.ts", "app/src/preview/a.tsx", "docs/design/README.md"]
)
def test_a_visible_change_needs_the_maintainer(path):
    ok, reasons = _decide(files=[path])
    assert not ok and reasons == ["Needs the maintainer: look at it"]


def _run(checks, body="- [x] done", files=FILES):
    calls = []

    def run(args):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return {"headRefOid": "H", "body": body}
        assert "--slurp" in args  # --paginate alone concatenates the pages' objects
        if "/files" in args[-1]:
            return [[{"filename": f} for f in files[:100]], [{"filename": f} for f in files[100:]]]
        return [{"check_runs": checks[:1]}, {"check_runs": checks[1:]}]

    return run, calls


def test_main_reports_ok_and_drops_the_verify_check(capsys):
    run, calls = _run([_check("tests"), _check("verify", status="in_progress", conclusion=None)])
    assert decide.main(["7"], run) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": True, "reasons": [], "sha": "H"}
    assert calls[0][:3] == ["pr", "view", "7"]
    assert any("commits/H/check-runs" in " ".join(c) for c in calls)


def test_main_exits_1_for_a_visible_file(capsys):
    run, _ = _run([_check("tests")], files=["docs/design/README.md"])
    assert decide.main(["7"], run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["reasons"] == ["Needs the maintainer: look at it"]


def test_main_reads_every_page_of_check_runs(capsys):
    run, _ = _run([_check("tests"), _check("app", conclusion="failure")])
    assert decide.main(["7"], run) == 1
    assert "check app failed" in json.loads(capsys.readouterr().out)["reasons"]


@pytest.mark.parametrize("line", ["+ [ ] x", "1. [ ] x", "  * [ ] x"])
def test_every_task_list_marker_counts_as_a_box(line):
    assert "unticked box" in _decide(body=line)[1]


def test_a_tilde_fence_hides_its_boxes():
    assert _decide(body="~~~\n- [ ] x\n~~~") == (True, [])


@pytest.mark.parametrize("line", ["- Needs the maintainer: try it", "**Needs the maintainer:** try it"])
def test_a_needs_the_maintainer_line_in_a_list_or_in_bold_is_seen(line):
    assert _decide(body=line) == (False, ["Needs the maintainer: try it"])


def test_main_reads_every_changed_file_past_the_first_hundred(capsys):
    run, _ = _run([_check("tests")], files=[f"src/door/f{i}.py" for i in range(150)] + ["app/src/web/x.ts"])
    assert decide.main(["7"], run) == 1
    assert json.loads(capsys.readouterr().out)["reasons"] == ["Needs the maintainer: look at it"]


def test_main_says_when_gh_fails(capsys):
    def run(args):
        raise decide.subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 404")

    assert decide.main(["7"], run) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "gh failed" in out["reasons"][0]


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
