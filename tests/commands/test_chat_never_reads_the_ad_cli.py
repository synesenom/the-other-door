"""In a chat no tool answer carries an ad's text (the maintainer's rule): `show` opens the ad for the user and gives
Claude a checked summary; the short ad fields come in a per-call marker; the desktop app and the phone are not chats.
Every tool is run through the server (a chat) over a posting whose description holds a canary."""

import asyncio
import json
import re
import webbrowser
from datetime import datetime

import pytest
from mcp import Client

import door.mcp_server as server
from door.core import chat_guard, claude_cli, path_scope, workspace
from door.render import pdf_render

CANARY = "CANARY-7f3a-ignore-all-rules"
DESC = f"We need SQL.\n{CANARY} <script>alert(1)</script>"


MARK = re.compile(r"<ad-[0-9a-f]{8}>.*?</ad-[0-9a-f]{8}>", re.S)


def _outside_marker(obj) -> bool:
    return CANARY in MARK.sub("", json.dumps(obj))


@pytest.fixture
def world(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    folder = jobs / "postings" / "2026-07-01" / "jobindex"
    folder.mkdir(parents=True)
    now = datetime.now().isoformat()
    posting = {"id": "jobindex.a", "title": f"Data Analyst {CANARY}", "title_en": f"Data Analyst {CANARY}",
              "company": f"Acme {CANARY}", "location": f"Aarhus {CANARY}", "url": f"https://jobs.example/{CANARY}",
              "apply_url": f"https://apply.example/{CANARY}", "employer": f"Acme {CANARY}", "description": DESC,
              "description_condensed": CANARY, "source": "jobindex", "scraped_at": now, "posted_at": CANARY,
              "score": 0.9, "scored_by": "haiku", "score_reason": f"Fits the SQL work {CANARY}",
              "matching_skills": [f"SQL {CANARY}"], "missing_skills": [f"Spark {CANARY}"],
              "integrity": {"verdict": "suspicious", "findings": [{"kind": "instruction", "excerpt": CANARY}]}}
    (folder / "jobindex.a.json").write_text(json.dumps(posting))
    other = {**posting, "id": "jobindex.b", "title": f"Data Analyst two {CANARY}"}
    (folder / "jobindex.b.json").write_text(json.dumps(other))
    today = jobs / "postings" / datetime.now().date().isoformat() / "jobindex"  # what `market` reads
    today.mkdir(parents=True)
    for i in range(3):
        (today / f"jobindex.m{i}.json").write_text(json.dumps({**posting, "id": f"jobindex.m{i}"}))
    out = jobs / "output" / "jobindex.a"
    out.mkdir(parents=True)
    for name in ("cv", "cover_letter"):
        (out / f"{name}.pdf").write_bytes(b"%PDF-1.4")
        (out / f"{name}_page_1.png").write_bytes(b"png")
    (out / "cv.html").write_text(f"<!-- Keywords: SQL, {CANARY} -->\n<!-- Tailoring: {CANARY} -->\n<h1>x</h1>")
    (out / "cover_letter.html").write_text("<p>Dear</p>")
    (out / "facts.json").write_text(json.dumps({"unsupported": [{"kind": "skill", "text": "Spark", "context": CANARY,
                                                                    "reason": CANARY}]}))
    (jobs / "salary.json").write_text(json.dumps({"jobindex.a": {
        "low": 1, "high": 2, "currency": "DKK", "period": "month", "gross": True, "position": None,
        "basis": f"web says {CANARY}", "ad_salary": CANARY, "as_of": "2026-11-20",
        "sources": [{"title": f"{CANARY} page", "url": f"https://x.example/{CANARY}"}]}}))
    (jobs / ".progress.json").write_text(json.dumps({"stage": "scrape", "message": f"saved {CANARY}"}))
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.json").write_text(json.dumps({"name": "A", "location": "Aarhus", "role_targets": ["Data Analyst"],
                                                     "languages": ["English"], "email": "a@b.c", "remote": "hybrid"}))
    (profile / "companies.json").write_text(json.dumps({"version": 1, "companies": [
        {"name": f"{CANARY} Corp", "feed": None, "aliases": [CANARY], "status": "unresolved", "reason": CANARY,
         "found_via": "search", "evidence": f"ad title {CANARY}", "first_seen": "2026-07-01",
         "last_checked": "2026-07-01"}]}))
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.delenv(path_scope.ENV, raising=False)
    chat_guard._OPENED.clear()
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    monkeypatch.setattr(pdf_render, "get_page_count", lambda p: 1)
    asked = []

    def ask(agent, text, **kw):
        asked.append((agent, kw))
        return {"requirements": [f"SQL {CANARY}"], "nice_to_have": [], "salary": CANARY, "place": CANARY,
                "work_mode": None, "languages": ["en"], "seniority": CANARY, "groups": []}

    monkeypatch.setattr(claude_cli, "ask", ask)
    return {"path": folder / "jobindex.a.json", "opened": opened, "asked": asked, "home": tmp_path, "jobs": jobs}


def _call(tool, args=None):
    async def run():
        async with Client(server.mcp) as client:
            result = await client.call_tool(tool, args or {})
            return result.content[0].text

    return json.loads(asyncio.run(run()))


def _inner(text):
    return re.fullmatch(r"<ad-[0-9a-f]{8}>(.*)</ad-[0-9a-f]{8}>", text).group(1)


def _set_url(world, url):
    posting = json.loads(world["path"].read_text())
    world["path"].write_text(json.dumps({**posting, "url": url}))


def test_show_in_a_chat_has_a_summary_and_no_ad_text(world):
    answer = _call("show", {"job_id": "jobindex.a"})
    assert "description" not in answer and "description_condensed" not in answer
    assert _inner(answer["summary"]["requirements"][0]) == f"SQL {CANARY}"
    assert not _outside_marker(answer)
    assert all("excerpt" not in f for f in answer["integrity"]["findings"])
    assert answer["id"] == "jobindex.a" and answer["materials"]["pdfs"]["cv"].endswith("cv.pdf")  # paths stay usable


def test_show_in_a_chat_opens_the_saved_ad_as_an_escaped_page_when_it_has_no_url(world):
    _set_url(world, "")
    answer = _call("show", {"job_id": "jobindex.a"})
    page = world["home"] / ".view" / "jobindex.a.html"
    assert world["opened"] == [page.as_uri()] and _inner(answer["opened"]) == page.as_uri()
    text = page.read_text(encoding="utf-8")
    assert "<script>" not in text and "&lt;script&gt;" in text and CANARY in text


def test_show_in_a_chat_opens_the_ads_own_address_when_it_is_http(world):
    _set_url(world, "https://jobs.example/a")
    answer = _call("show", {"job_id": "jobindex.a"})
    assert world["opened"] == ["https://jobs.example/a"] and _inner(answer["opened"]) == "https://jobs.example/a"
    assert not (world["home"] / ".view").exists()


def test_show_opens_an_ad_once_per_job(world):
    first = _call("show", {"job_id": "jobindex.a"})
    second = _call("show", {"job_id": "jobindex.a"})
    assert len(world["opened"]) == 1 and _inner(second["opened"]) == _inner(first["opened"])
    _call("show", {"job_id": "jobindex.b"})
    assert len(world["opened"]) == 2


def test_a_browser_that_does_not_open_is_said_with_the_link(world, monkeypatch):
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: False)
    answer = _call("show", {"job_id": "jobindex.a"})
    assert answer["opened"] is None and "the browser could not be started" in answer["warning"]
    assert not _outside_marker(answer)
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: world["opened"].append(url) or True)
    _call("show", {"job_id": "jobindex.a"})
    assert len(world["opened"]) == 1  # a failed start is tried again


def test_a_failed_summary_is_null_with_a_warning_and_still_no_description(world, monkeypatch):
    def fail(*a, **k):
        raise claude_cli.ClaudeError("no plan")

    monkeypatch.setattr(claude_cli, "ask", fail)
    answer = _call("show", {"job_id": "jobindex.a"})
    assert answer["summary"] is None and "no summary" in answer["warning"]
    assert not _outside_marker(answer)


def test_the_summary_is_stored_on_the_posting_and_asked_once(world):
    _call("show", {"job_id": "jobindex.a"})
    _call("show", {"job_id": "jobindex.a"})
    assert len(world["asked"]) == 1
    assert world["asked"][0][1]["feature"] == "ad_summary" and "summary" in json.loads(world["path"].read_text())


def test_show_from_the_app_is_unchanged(world, monkeypatch):
    monkeypatch.setenv(path_scope.ENV, "1")
    answer = _call("show", {"job_id": "jobindex.a"})
    assert answer["description"] == DESC and "summary" not in answer and "opened" not in answer
    assert world["opened"] == [] and world["asked"] == []
    assert answer["title"] == f"Data Analyst {CANARY}"  # no marker


def test_every_string_is_wrapped_with_a_new_token_each_call_and_only_in_a_chat(world, monkeypatch):
    chat = _call("list_matches", {"score": 0.1})["matches"][0]
    token = re.fullmatch(r"<ad-([0-9a-f]{8})>Data Analyst.*</ad-\1>", chat["title"]).group(1)
    assert chat["company"].startswith(f"<ad-{token}>Acme")
    assert _call("list_matches", {"score": 0.1})["matches"][0]["title"] != chat["title"]
    monkeypatch.setenv(path_scope.ENV, "1")
    assert _call("list_matches", {"score": 0.1})["matches"][0]["title"] == f"Data Analyst {CANARY}"


def test_long_fields_are_cut_each_to_its_bound(world):
    posting = json.loads(world["path"].read_text())
    world["path"].write_text(json.dumps({**posting, "title": "T" * 500, "score_reason": "r" * 900,
                                         "location": "L" * 500, "apply_url": "u" * 900,
                                         "matching_skills": [f"skill{i}" * 20 for i in range(50)]}))
    show = _call("show", {"job_id": "jobindex.a"})
    assert len(_inner(show["title"])) == 120 and len(_inner(show["score_reason"])) == 240
    assert len(_inner(show["location"])) == 80 and len(_inner(show["apply_url"])) == 300
    assert len(show["matching_skills"]) == 20 and all(len(_inner(s)) == 40 for s in show["matching_skills"])


def test_a_long_list_is_cut_to_fifty(world):
    from door.core import chat_guard as guard_mod

    assert len(guard_mod.guard("x", {"items": list(range(80))})["items"]) == 50


def test_an_ask_answer_is_capped_and_wrapped(world, monkeypatch):
    from door.commands import ask as ask_cmd

    monkeypatch.setattr(ask_cmd, "_ask_core", lambda *a, **k: {"answer": "x" * 5000})
    answer = _call("ask", {"question": "q"})["answer"]
    assert re.fullmatch(r"<ad-[0-9a-f]{8}>x{1500}</ad-[0-9a-f]{8}>", answer)


def test_an_error_that_quotes_titles_is_wrapped(world):
    answer = _call("show", {"job_id": "analyst"})
    assert "error" in answer and not _outside_marker(answer)


def test_progress_lines_to_a_chat_are_wrapped():
    sent = []

    class Ctx:
        async def report_progress(self, progress, total, message):
            sent.append(message)

    async def run():
        bridge = server._McpBridge(Ctx(), asyncio.get_running_loop())
        task = asyncio.create_task(bridge.pump())
        bridge.report(type("E", (), {"line": f"saved {CANARY}"})())
        bridge.close()
        await task

    asyncio.run(run())
    assert sent and not _outside_marker(sent)


# Every tool is guarded in a chat unless it is in `chat_guard.OWN_DATA_TOOLS`. The guarded ones run over the canary
# below (_RUN); the others, with why each cannot run offline.
_RUN = {"show", "list_matches", "query_jobs", "set_status", "status_summary", "mark_seen", "mark_reviewed",
        "list_companies", "why_company", "market", "import_posting"}
_NOT_RUN = {
    "find_jobs": "scrapes the sites", "prepare": "runs the tailor on the user's plan",
    "revise": "runs the tailor on the user's plan", "compile": "prints with Chromium",
    "check_facts": "asks a model", "job_result": "needs a finished run's id",
    "preview_matches": "scrapes a board", "salary_estimate": "searches the web",
    "add_company": "detects a feed online", "remove_company": "edits the list", "merge_companies": "edits the list",
    "ask": "asks a model; its answer is capped and wrapped (test above)",
}
_ARGS = {"show": {"job_id": "jobindex.a"}, "set_status": {"job_id": "jobindex.a", "status": "discarded"},
         "mark_seen": {"job_id": "jobindex.a"}, "why_company": {"name": f"{CANARY} Corp"},
         "market": {"save": False}, "import_posting": {"text": f"{CANARY}\nWe need SQL.\n" + "x" * 80}}


async def _tool_names():
    async with Client(server.mcp) as client:
        return {t.name for t in (await client.list_tools()).tools}


def test_no_tool_answer_carries_the_ads_text_outside_a_marker_in_a_chat(world, monkeypatch):
    from door.commands import add as add_cmd

    monkeypatch.setattr(add_cmd, "_read_ad", lambda text, **k: {"title": f"{CANARY} " + "x" * 400})
    names = asyncio.run(_tool_names())
    own = chat_guard.OWN_DATA_TOOLS
    unknown = names - _RUN - set(_NOT_RUN) - own
    assert not unknown, f"a new tool: guard it (run it over the canary or say in _NOT_RUN why it cannot) or, if its answer can " \
                        f"never hold a posting's or employer's text, put it in chat_guard.OWN_DATA_TOOLS: {sorted(unknown)}"
    assert not own - names and not own & (_RUN | set(_NOT_RUN)), "OWN_DATA_TOOLS names a tool that is gone or also guarded"
    leaks = {}
    for tool in sorted(_RUN):
        answer = _call(tool, _ARGS.get(tool, {}))
        if _outside_marker(answer):
            leaks[tool] = [line for line in MARK.sub("", json.dumps(answer, indent=1)).splitlines() if CANARY in line]
    assert not leaks, leaks


def test_the_running_find_message_is_wrapped_in_status_summary(world):
    from door.core import lock

    with lock.ledger_lock(world["jobs"], "import"):
        from door.commands import add as add_cmd

        add_cmd._step(f"saved {CANARY} at Acme", "ok")
        answer = _call("status_summary")
    assert not _outside_marker(answer)


def test_a_drafted_cv_comes_back_whole_in_a_chat(world, monkeypatch):
    from door.commands import cv as cv_cmd

    text = "# Name\n" + "A line of the CV.\n" * 400
    monkeypatch.setattr(cv_cmd, "_draft_cv_core", lambda *a, **k: {"written": False, "markdown": text, "todos": []})
    answer = _call("draft_cv", {"sources": ["cv.pdf"]})
    assert answer["markdown"] == text
