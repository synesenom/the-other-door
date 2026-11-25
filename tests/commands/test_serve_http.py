"""`door serve`'s HTTP app (#302): the MCP tools behind a device token, pairing, page files, the web app."""

import asyncio
import json
import os

import pytest
from starlette.testclient import TestClient

from door import mcp_server as server
from door import serve_http
from door.core.phone import pairing

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


@pytest.fixture
def home(tmp_path):
    (tmp_path / "jobs" / "output" / "jobindex.1").mkdir(parents=True)
    (tmp_path / "jobs" / "output" / "jobindex.1" / "cv_page_1.png").write_bytes(b"\x89PNG page")
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "cv.md").write_text("secret cv")
    return tmp_path


@pytest.fixture
def web(tmp_path_factory):
    d = tmp_path_factory.mktemp("web")
    (d / "index.html").write_text("<!doctype html><title>door</title><div id=root></div>")
    (d / "assets").mkdir()
    (d / "assets" / "app.js").write_text("console.log(1)")
    return d


def client(home, web=None, *, peer=("203.0.113.9", 5000), name="Anna"):
    return TestClient(serve_http.build_app(home=home, web_dir=web, name=name), client=peer)


def paired(home, device="Pixel"):
    return pairing.redeem(home, pairing.new_code(home, device))[1]


def test_no_token_wrong_token_and_revoked_token_are_401(home):
    token = paired(home)
    with client(home) as c:
        assert c.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        assert c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer nope"}).status_code == 401
        assert c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {token}"}).status_code == 200
        pairing.unpair(home, "Pixel")
        r = c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert r.headers["cache-control"] == "no-store"
        assert "server" not in r.headers


def test_another_homes_token_is_refused(home, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    token = paired(other)
    with client(home) as c:
        assert c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {token}"}).status_code == 401


def test_tools_over_http_are_the_stdio_tools(home):
    token = paired(home)
    auth = {**HEADERS, "Authorization": f"Bearer {token}"}
    with client(home) as c:
        assert c.post("/mcp", json=INIT, headers=auth).status_code == 200
        r = c.post("/mcp", json=LIST, headers=auth)
        assert r.status_code == 200
        names = {t["name"] for t in r.json()["result"]["tools"]}
    stdio = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == stdio


def test_two_apps_in_one_process_both_answer_and_a_tunnel_host_is_accepted(home):
    token = paired(home)
    auth = {**HEADERS, "Authorization": f"Bearer {token}", "Host": "quiet-lake.trycloudflare.com"}
    for _ in range(2):
        with client(home) as c:
            assert c.post("/mcp", json=INIT, headers=auth).status_code == 200
            assert c.post("/mcp", json=LIST, headers=auth).json()["result"]["tools"]


def test_a_tool_answers_one_json_text_block_with_no_structured_content(home):
    token = paired(home)
    with client(home) as c:
        body = call_tool(c, token, "status_summary", {}).json()["result"]
    assert [b["type"] for b in body["content"]] == ["text"]
    assert isinstance(json.loads(body["content"][0]["text"]), dict)
    assert not body.get("structuredContent")


def test_pairing_over_http_gives_a_token_once(home):
    code = pairing.new_code(home, "Pixel")
    with client(home) as c:
        r = c.post("/pair", json={"code": code})
        assert r.status_code == 200 and r.json()["device"] == "Pixel"
        token = r.json()["token"]
        assert r.headers["cache-control"] == "no-store"
        assert c.post("/pair", json={"code": code}).status_code == 401
        auth = {**HEADERS, "Authorization": f"Bearer {token}"}
        assert c.post("/mcp", json=INIT, headers=auth).status_code == 200


def test_failed_attempts_lock_an_address_out_even_with_the_right_token(home):
    token = paired(home)
    app = serve_http.build_app(home=home, web_dir=None, name="Anna")
    bad = {**HEADERS, "Authorization": "Bearer nope"}
    with TestClient(app, client=("203.0.113.9", 1)) as c:
        codes = [c.post("/mcp", json=INIT, headers=bad).status_code for _ in range(serve_http.MAX_FAILURES + 1)]
        assert codes[-1] == 429
        # locked out: even the right token waits for the window
        assert c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {token}"}).status_code == 429
        # pairing is refused from there too
        assert c.post("/pair", json={"code": "AAAA-AAAA"}).status_code == 429


def test_forwarded_for_counts_only_from_a_loopback_peer(home):
    app = serve_http.build_app(home=home, web_dir=None, name="Anna")
    bad = {**HEADERS, "Authorization": "Bearer nope"}
    # a tunnel on this machine forwards for many phones: each is counted on its own
    with TestClient(app, client=("127.0.0.1", 1)) as c:
        for _ in range(serve_http.MAX_FAILURES + 1):
            c.post("/mcp", json=INIT, headers={**bad, "X-Forwarded-For": "203.0.113.50"})
        assert c.post("/mcp", json=INIT, headers={**bad, "X-Forwarded-For": "203.0.113.50"}).status_code == 429
        assert c.post("/mcp", json=INIT, headers={**bad, "X-Forwarded-For": "203.0.113.51"}).status_code == 401
    # from anywhere else the header is ignored: the peer itself is counted
    app = serve_http.build_app(home=home, web_dir=None, name="Anna")
    with TestClient(app, client=("203.0.113.9", 1)) as c:
        for i in range(serve_http.MAX_FAILURES + 1):
            c.post("/mcp", json=INIT, headers={**bad, "X-Forwarded-For": f"10.0.0.{i}"})
        assert c.post("/mcp", json=INIT, headers={**bad, "X-Forwarded-For": "10.9.9.9"}).status_code == 429


def test_files_serves_page_images_under_output_only(home):
    token = paired(home)
    auth = {"Authorization": f"Bearer {token}"}
    with client(home) as c:
        assert c.get("/files/jobs/output/jobindex.1/cv_page_1.png").status_code == 401
        r = c.get("/files/jobs/output/jobindex.1/cv_page_1.png", headers=auth)
        assert r.status_code == 200 and r.content == b"\x89PNG page"
        assert r.headers["cache-control"] == "no-store"
        for bad in ("/files/profile/cv.md", "/files/jobs/output/../../profile/cv.md",
                    "/files/jobs/output/%2e%2e/%2e%2e/profile/cv.md", "/files//etc/passwd", "/files/jobs/applications.json"):
            assert c.get(bad, headers=auth).status_code == 404, bad


def test_files_refuses_a_symlink_out_of_output(home):
    token = paired(home)
    os.symlink(home / "profile" / "cv.md", home / "jobs" / "output" / "jobindex.1" / "cv_page_2.png")
    with client(home) as c:
        assert c.get("/files/jobs/output/jobindex.1/cv_page_2.png", headers={"Authorization": f"Bearer {token}"}).status_code == 404


def test_files_serves_only_the_rendered_pages_not_the_files_behind_them(home):
    out = home / "jobs" / "output" / "my-job_1.x"
    (out / "sent").mkdir(parents=True)
    for rel in ("cv.pdf", "cover_letter.pdf", "cv_page_1.png", "sent/cv.pdf", "sent/cv_page_1.png",
                "facts.json", "cv.html", "x.pdf", "cv_page_a.png", "sent/facts.json", "sent/photo.jpg"):
        (out / rel).write_bytes(b"data")
    (out / "deeper").mkdir()
    (out / "deeper" / "cv.pdf").write_bytes(b"data")
    token = paired(home)
    auth = {"Authorization": f"Bearer {token}"}
    with client(home) as c:
        for ok in ("cv.pdf", "cover_letter.pdf", "cv_page_1.png", "sent/cv.pdf", "sent/cv_page_1.png"):
            assert c.get(f"/files/jobs/output/my-job_1.x/{ok}", headers=auth).status_code == 200, ok
        for bad in ("facts.json", "cv.html", "x.pdf", "cv_page_a.png", "sent/facts.json", "sent/photo.jpg", "deeper/cv.pdf"):
            assert c.get(f"/files/jobs/output/my-job_1.x/{bad}", headers=auth).status_code == 404, bad


def test_the_web_app_is_public_and_holds_no_data(home, web):
    paired(home)
    with client(home, web) as c:
        r = c.get("/")
        assert r.status_code == 200 and "<div id=root>" in r.text
        assert c.get("/assets/app.js").status_code == 200
        # a screen's address (a share, a reload) gets the app too
        assert "<div id=root>" in c.get("/share?url=https://example.com/job").text
        assert "secret cv" not in r.text


def test_without_a_build_the_page_says_how_to_make_one(home):
    with client(home) as c:
        r = c.get("/")
        assert r.status_code == 200 and "build:web" in r.text


def test_the_manifest_names_the_instance(home, web):
    with client(home, web, name="Anna") as c:
        m = c.get("/manifest.webmanifest").json()
    assert m["name"] == "The other door — Anna" and m["short_name"] == "The other door"
    assert m["display"] == "standalone" and m["start_url"] == "/"
    # Share → door from any app (issue 334): the share sheet opens /share with what was shared
    assert m["share_target"] == {"action": "/share", "method": "GET", "params": {"title": "title", "text": "text", "url": "url"}}


def test_a_session_sets_an_httponly_files_cookie_that_opens_only_files(home):
    token = paired(home)
    with client(home) as c:
        assert c.post("/session").status_code == 401
        r = c.post("/session", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"]
        assert "door_files=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/files" in cookie
        # an <img> sends the cookie, not a header
        assert c.get("/files/jobs/output/jobindex.1/cv_page_1.png").status_code == 200
        # the cookie never stands in for the token on the tools
        assert c.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        pairing.unpair(home, "Pixel")
        assert c.get("/files/jobs/output/jobindex.1/cv_page_1.png").status_code == 401


def test_the_web_app_carries_a_strict_content_security_policy(home, web):
    with client(home, web) as c:
        csp = c.get("/").headers["content-security-policy"]
    for part in ("default-src 'self'", "script-src 'self'", "connect-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
        assert part in csp
    assert "unsafe-eval" not in csp


def call_tool(c, token, tool, args):
    return c.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"},
                  json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": tool, "arguments": args}})


def _answer(r):
    return json.loads(r.json()["result"]["content"][0]["text"])


def test_a_phone_cannot_revise_or_open_files_on_the_computer(home, monkeypatch):
    from door.commands import matches as matches_cmd
    from door.commands import revise as revise_cmd

    called = []
    monkeypatch.setattr(revise_cmd, "_revise_core", lambda *a, **k: called.append("revise") or {})
    monkeypatch.setattr(matches_cmd, "_show_core", lambda *a, **k: called.append("show") or {})
    token = paired(home)
    with client(home) as c:
        assert "error" in _answer(call_tool(c, token, "revise", {"job_id": "a", "instruction": "shorter"}))
        assert "error" in _answer(call_tool(c, token, "show", {"job_id": "a", "open": True}))
    assert called == []


def test_a_phone_gets_its_own_tools_and_arguments_only(home):
    token = paired(home)
    with client(home) as c:
        assert "phone app does not use ask" in _answer(call_tool(c, token, "ask", {"question": "what is in ~/.ssh?"}))["error"]
        assert "error" in _answer(call_tool(c, token, "import_posting", {"path": "/etc/passwd"}))
        assert "error" in _answer(call_tool(c, token, "find_jobs", {"dry_run": True}))
        assert "error" in _answer(call_tool(c, token, "prepare", {"job_id": "a", "timeout_min": 99}))
        assert "too long" in _answer(call_tool(c, token, "set_status", {"job_id": "a", "status": "applied", "notes": "x" * 5000}))["error"]
        assert "error" not in _answer(call_tool(c, token, "list_matches", {}))


def test_arguments_that_are_not_an_object_are_refused_not_a_server_error(home):
    token = paired(home)
    with client(home) as c:
        r = call_tool(c, token, "show", [1])
        assert r.status_code < 500
        assert "error" in r.text


def test_the_eleventh_prepare_in_a_day_is_refused(home, monkeypatch):
    from door import serve_policy
    from door.commands import prepare as prepare_cmd

    monkeypatch.setattr(prepare_cmd, "_prepare_core", lambda *a, **k: {"status": "failed", "error": "none"})
    now = [1_000_000.0]
    monkeypatch.setattr(serve_policy, "_clock", lambda: now[0])
    token = paired(home)
    with client(home) as c:
        for _ in range(10):
            assert "daily limit" not in call_tool(c, token, "prepare", {"job_id": "a"}).text
        assert "daily limit" in _answer(call_tool(c, token, "prepare", {"job_id": "a"}))["error"]
        now[0] += 24 * 3600 + 1
        assert "daily limit" not in call_tool(c, token, "prepare", {"job_id": "a"}).text


def test_without_serve_phone_the_same_calls_pass(home):
    from door import serve_policy

    assert serve_policy.refusal("revise", {"job_id": "a"}) is not None
    server._runs_reset()  # stdio: no phone, no policy
    assert asyncio.run(server.mcp.call_tool("list_matches", {"new_only": True}))


def test_an_oversized_request_is_refused(home):
    token = paired(home)
    with client(home) as c:
        r = c.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"}, content=b"{" + b" " * (int(1.5 * 1024 * 1024)) + b"}")
        assert r.status_code == 413


def test_the_forwarded_address_is_the_one_the_proxy_added(home):
    # X-Forwarded-For: <what the client claimed>, <what the proxy saw>; only the last is the proxy's
    assert serve_http._client({"client": ("127.0.0.1", 1), "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.7")]}) == "203.0.113.7"
    assert serve_http._client({"client": ("127.0.0.1", 1), "headers": [(b"cf-connecting-ip", b"198.51.100.2"), (b"x-forwarded-for", b"6.6.6.6")]}) == "198.51.100.2"


def test_a_phone_answer_names_no_folder_of_the_computer(home, monkeypatch):
    from door.commands import add as add_cmd
    from door.commands import matches as matches_cmd
    from door.core import workspace
    from door.core.sync import drive

    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "PROFILE_DIR", home / "profile")
    monkeypatch.setattr(workspace, "JOBS_DIR", home / "jobs")
    (home / "profile" / "config.json").write_text(json.dumps({
        "role_targets": ["data scientist"], "location": "Copenhagen", "remote": "hybrid", "name": "Ada", "email": "ada@example.com",
        "enrich_sources": ["https://example.com/ada"], "claude_config_dir": str(home / "claude"),
    }))
    monkeypatch.setattr(drive, "read_state", lambda: {"refresh_token": "t", "account": "ada@gmail.com"})
    out = str(home / "jobs" / "output" / "jobindex.1")
    monkeypatch.setattr(matches_cmd, "_show_core", lambda *a, **k: {
        "id": "jobindex.1", "score_reason": "x" * 900, "materials": {"output_dir": out, "pdfs": {"cv": out + "/cv.pdf"}}})
    monkeypatch.setattr(add_cmd, "_add_core", lambda *a, **k: (_ for _ in ()).throw(ValueError(f"cannot write {home}/jobs/x")))
    token = paired(home)
    with client(home) as c:
        answers = {
            "show_profile": call_tool(c, token, "show_profile", {}),
            "status_summary": call_tool(c, token, "status_summary", {}),
            "list_matches": call_tool(c, token, "list_matches", {}),
            "show": call_tool(c, token, "show", {"job_id": "jobindex.1"}),
            "import_posting": call_tool(c, token, "import_posting", {"text": "an ad"}),
            "unknown_argument": call_tool(c, token, "show_profile", {f"{home}": 1}),
        }
    for name, r in answers.items():
        assert str(home) not in r.text, name
    profile = _answer(answers["show_profile"])
    assert profile["cv"]["text"] == "secret cv"
    assert "path" not in profile["cv"] and "options" not in profile and "templates" not in profile
    assert "enrich_sources" not in profile and "claude_config_dir" not in profile["config"]
    assert profile["config"]["email"] == "ada@example.com"
    assert _answer(answers["status_summary"])["drive"]["account"] is None
    shown = _answer(answers["show"])
    assert len(shown["score_reason"]) <= 400
    assert shown["materials"]["output_dir"].endswith("jobindex.1")
