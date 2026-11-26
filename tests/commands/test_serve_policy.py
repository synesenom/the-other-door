"""What a phone may ask `door serve` for (#302, #544): its own tools with the app's arguments, capped, within
a daily ceiling; no prompt to Claude, no revise."""

import asyncio
import json

import pytest

from door import mcp_server as server
from door import serve_policy as policy

PHONE = {
    "status_summary", "show_profile", "find_jobs", "cancel_job", "list_matches", "show", "mark_seen", "job_result",
    "set_status", "prepare", "import_posting",
}


def test_the_phone_tools_are_real_tools_finding_preparing_and_the_applications():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert set(policy.PHONE_TOOLS) <= names
    assert set(policy.PHONE_TOOLS) == PHONE


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(policy, "_clock", lambda: now[0])
    return now


@pytest.mark.parametrize("tool", [
    "ask", "setup", "export_data", "import_data", "draft_cv", "compile", "connect_drive", "query_jobs",
    "init_profile", "save_cv", "keywords", "enrich", "market",
    "list_stories", "save_story", "remove_story", "draft_stories",
    "list_companies", "why_company", "add_company", "remove_company", "merge_companies",
    "doctor", "sync_data", "disconnect_drive", "revise", "mark_reviewed",
])
def test_a_tool_the_phone_does_not_use_is_refused(tool):
    assert "phone" in policy.refusal(tool, {})


def test_everyday_calls_pass():
    for tool, args in [
        ("list_matches", {"ongoing": True}), ("list_matches", {"closed": True}), ("list_matches", {}),
        ("show", {"job_id": "a"}), ("prepare", {"job_id": "a", "force": True}), ("find_jobs", {}), ("find_jobs", None),
        ("import_posting", {"url": "https://jobs.example.com/1"}),
        ("import_posting", {"text": "an ad", "title": "t", "company": "c", "location": "l", "url": "https://x.example", "force": True}),
        ("set_status", {"job_id": "a", "status": "applied", "notes": "x" * 2000}), ("job_result", {"tool": "prepare"}),
        ("mark_seen", {"job_id": "a"}), ("show_profile", {}), ("status_summary", {}), ("cancel_job", {}),
    ]:
        assert policy.refusal(tool, args) is None, (tool, args)


@pytest.mark.parametrize("tool, args", [
    ("show", {"job_id": "a", "open": True}),
    ("prepare", {"job_id": "a", "timeout_min": 5}),
    ("find_jobs", {"boards": "jobindex"}),
    ("import_posting", {"path": "/Users/ada/.ssh/id_ed25519"}),
    ("list_matches", {"new_only": True}),
    ("set_status", {"job_id": "a", "status": "applied", "notes": "x" * 5000}),
    ("import_posting", {"text": "x" * 30001}),
    ("import_posting", {"url": "https://x.example/" + "a" * 2000}),
    ("show", {"job_id": "a" * 301}),
])
def test_an_argument_the_app_does_not_send_or_a_string_too_long_is_refused(tool, args):
    assert policy.refusal(tool, args)


def test_the_longest_ad_passes():
    assert policy.refusal("import_posting", {"text": "x" * 30000}) is None


def test_arguments_that_are_not_an_object_are_refused_not_raised():
    assert policy.refusal("show", [1])


def test_a_phone_cannot_name_a_path():
    assert policy.refusal("import_posting", {"path": "/Users/ada/.ssh/id_ed25519"})


@pytest.mark.parametrize("tool, args, limit", [
    ("prepare", {"job_id": "a"}, 10), ("import_posting", {"text": "an ad"}, 30), ("find_jobs", {}, 6),
])
def test_a_tool_that_costs_has_a_daily_ceiling_over_a_rolling_day(clock, tool, args, limit):
    for _ in range(limit):
        assert policy.refusal(tool, args) is None
    assert "daily limit" in policy.refusal(tool, args)
    clock[0] += 24 * 3600 + 1
    assert policy.refusal(tool, args) is None


def test_a_refused_call_is_not_counted(clock):
    for _ in range(20):
        assert policy.refusal("prepare", {"job_id": "a", "timeout_min": 1})
    for _ in range(10):
        assert policy.refusal("prepare", {"job_id": "a"}) is None


def test_mask_hides_the_folders_of_the_computer_keeping_the_file_names(tmp_path, monkeypatch):
    from pathlib import Path

    from door.core import workspace

    data = tmp_path / "data"
    monkeypatch.setattr(workspace, "HOME", data)
    monkeypatch.setenv("DOOR_HOME", str(tmp_path / "other"))
    text = f"{data}/jobs/output/a.1/cv.pdf and {tmp_path}/other/x and {Path.home()}/notes and {workspace.REPO_ROOT}/src"
    masked = policy.mask(text)
    for folder in (str(data), str(tmp_path / "other"), str(Path.home()), str(workspace.REPO_ROOT)):
        assert folder not in masked
    assert "cv.pdf" in masked and "/jobs/output/a.1/" in masked


def test_a_profile_answer_keeps_what_the_phone_reads_and_drops_the_rest(tmp_path, monkeypatch):
    from door.core import workspace

    monkeypatch.setattr(workspace, "HOME", tmp_path)
    answer = policy.answer("show_profile", {
        "path": str(tmp_path / "profile"), "options": {"cities": [1]}, "templates": {"cv": {}}, "enrich_sources": ["u"],
        "config": {"email": "a@b.c", "min_score": 0.5, "cv_content": str(tmp_path / "x"), "claude_config_dir": "/c"},
        "errors": [], "cv": {"path": str(tmp_path / "cv.md"), "text": "cv", "exists": True},
        "story_bank": {}, "photo": {}, "discovery_unchosen": ["linkedin"],
    })
    assert set(answer) == {"config", "errors", "cv", "discovery_unchosen"}
    assert answer["config"] == {"email": "a@b.c", "min_score": 0.5}
    assert answer["cv"] == {"text": "cv", "exists": True}
    assert policy.answer("show_profile", {"config": None, "errors": ["x"], "cv": {}, "discovery_unchosen": []})["config"] is None


def test_the_drive_account_and_a_long_reason_are_not_sent():
    summary = policy.answer("status_summary", {"drive": {"connected": True, "account": "a@b.c"}, "n": 1})
    assert summary["drive"] == {"connected": True, "account": None} and summary["n"] == 1
    assert policy.answer("status_summary", {"drive": None})["drive"] is None
    shown = policy.answer("show", {"score_reason": "y" * 900, "rows": [{"score_reason": "z" * 900}]})
    assert len(shown["score_reason"]) == 400 and len(shown["rows"][0]["score_reason"]) == 400


def test_paths_are_masked_in_every_string_however_deep(tmp_path, monkeypatch):
    from door.core import workspace

    monkeypatch.setattr(workspace, "HOME", tmp_path)
    shown = policy.answer("show", {"materials": {"pdfs": {"cv": f"{tmp_path}/jobs/output/a/cv.pdf"}, "list": [f"{tmp_path}/x"]}, "n": 3})
    assert str(tmp_path) not in json.dumps(shown) and shown["n"] == 3
