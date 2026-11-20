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
            return {"headRefOid": "H", "body": body, "files": [{"path": f} for f in files]}
        return {"check_runs": checks}

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
