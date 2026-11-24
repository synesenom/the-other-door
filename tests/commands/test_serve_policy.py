"""What a phone may ask `door serve` for (#302 hardening): its own tools only, no local paths, no prompt
to Claude."""

import pytest

from door import mcp_server as server
from door import serve_policy as policy


# What the phone app is for: finding new jobs, preparing them and the applications. Setting up and
# changing the profile, the CV and the employers is done on the computer running The other door.
PHONE = {
    "status_summary", "list_matches", "show", "set_status", "mark_reviewed", "mark_seen", "import_posting",
    "find_jobs", "job_result", "cancel_job", "prepare", "revise", "show_profile",
}


def test_the_phone_tools_are_real_tools_finding_preparing_and_the_applications():
    import asyncio

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert policy.PHONE_TOOLS <= names
    assert policy.PHONE_TOOLS == PHONE


@pytest.mark.parametrize("tool", [
    "ask", "setup", "export_data", "import_data", "draft_cv", "compile", "connect_drive", "query_jobs",
    # the profile, the CV and the employers are changed on the computer
    "init_profile", "save_cv", "keywords", "enrich", "skill_gaps", "market",
    "list_stories", "save_story", "remove_story", "draft_stories",
    "list_companies", "why_company", "add_company", "remove_company", "merge_companies",
    "doctor", "sync_data", "disconnect_drive",
])
def test_a_tool_the_phone_does_not_use_is_refused(tool):
    assert "phone" in policy.refusal(tool, {})


def test_everyday_calls_pass():
    for tool, args in [
        ("list_matches", {"new_only": True}), ("show", {"job_id": "a"}), ("prepare", {}), ("find_jobs", {}),
        ("import_posting", {"url": "https://jobs.example.com/1"}), ("import_posting", {"text": "an ad"}),
        ("revise", {"job_id": "a", "instruction": "shorter"}), ("set_status", {"job_id": "a", "status": "applied"}),
        ("show_profile", {}),
    ]:
        assert policy.refusal(tool, args) is None, (tool, args)


def test_no_local_file_path():
    assert "file" in policy.refusal("import_posting", {"path": "/Users/ada/.ssh/id_ed25519"})
