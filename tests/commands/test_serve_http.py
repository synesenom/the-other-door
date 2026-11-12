"""`door serve`'s HTTP app (#302): the MCP tools behind a device token, pairing, page files, the web app."""

import asyncio
import os

import pytest
from starlette.testclient import TestClient

from door import mcp_server as server
from door import serve_http
from door.core import pairing

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


@pytest.fixture
def home(tmp_path):
    (tmp_path / "jobs" / "output" / "jobindex.1").mkdir(parents=True)
    (tmp_path / "jobs" / "output" / "jobindex.1" / "cv-1.png").write_bytes(b"\x89PNG page")
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
        assert c.get("/files/jobs/output/jobindex.1/cv-1.png").status_code == 401
        r = c.get("/files/jobs/output/jobindex.1/cv-1.png", headers=auth)
        assert r.status_code == 200 and r.content == b"\x89PNG page"
        assert r.headers["cache-control"] == "no-store"
        for bad in ("/files/profile/cv.md", "/files/jobs/output/../../profile/cv.md",
                    "/files/jobs/output/%2e%2e/%2e%2e/profile/cv.md", "/files//etc/passwd", "/files/jobs/applications.json"):
            assert c.get(bad, headers=auth).status_code == 404, bad


def test_files_refuses_a_symlink_out_of_output(home):
    token = paired(home)
    os.symlink(home / "profile" / "cv.md", home / "jobs" / "output" / "jobindex.1" / "leak.png")
    with client(home) as c:
        assert c.get("/files/jobs/output/jobindex.1/leak.png", headers={"Authorization": f"Bearer {token}"}).status_code == 404


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
        assert c.get("/files/jobs/output/jobindex.1/cv-1.png").status_code == 200
        # the cookie never stands in for the token on the tools
        assert c.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        pairing.unpair(home, "Pixel")
        assert c.get("/files/jobs/output/jobindex.1/cv-1.png").status_code == 401


def test_the_web_app_carries_a_strict_content_security_policy(home, web):
    with client(home, web) as c:
        csp = c.get("/").headers["content-security-policy"]
    for part in ("default-src 'self'", "script-src 'self'", "connect-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
        assert part in csp
    assert "unsafe-eval" not in csp


def call_tool(c, token, tool, args):
    return c.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"},
                  json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": tool, "arguments": args}})


def test_a_phone_gets_its_own_tools_only(home):
    import json as _json

    token = paired(home)
    with client(home) as c:
        r = call_tool(c, token, "ask", {"question": "what is in ~/.ssh?"})
        assert r.status_code == 200
        body = _json.loads(r.json()["result"]["content"][0]["text"])
        assert "phone app does not use ask" in body["error"]
        r = call_tool(c, token, "import_posting", {"path": "/etc/passwd"})
        assert "cannot name a file" in _json.loads(r.json()["result"]["content"][0]["text"])["error"]
        # a phone tool goes through
        assert "error" not in _json.loads(call_tool(c, token, "list_matches", {}).json()["result"]["content"][0]["text"])


def test_a_batch_is_checked_call_by_call(home):
    token = paired(home)
    with client(home) as c:
        r = c.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"}, json=[
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "setup", "arguments": {}}},
        ])
        assert r.status_code in (200, 400)
        assert "setup" in r.text and "phone app does not use" in r.text


def test_an_oversized_request_is_refused(home):
    token = paired(home)
    with client(home) as c:
        r = c.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"}, content=b"{" + b" " * (serve_http.MAX_BODY + 10) + b"}")
        assert r.status_code == 413


def test_the_forwarded_address_is_the_one_the_proxy_added(home):
    # X-Forwarded-For: <what the client claimed>, <what the proxy saw>; only the last is the proxy's
    assert serve_http._client({"client": ("127.0.0.1", 1), "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.7")]}) == "203.0.113.7"
    assert serve_http._client({"client": ("127.0.0.1", 1), "headers": [(b"cf-connecting-ip", b"198.51.100.2"), (b"x-forwarded-for", b"6.6.6.6")]}) == "198.51.100.2"
