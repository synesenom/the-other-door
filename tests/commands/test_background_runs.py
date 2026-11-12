"""Runs that outlive the request (#302): over HTTP, find_jobs and prepare start and return at once;
`job_result` gives the finished run and `cancel_job` stops one. Over stdio they block as before."""

import asyncio
import threading
import time

import pytest
from starlette.testclient import TestClient

from door import mcp_server as server
from door import serve_http
from door.commands import find as find_cmd
from door.core import pairing
from door.core.progress import activate, report

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def fresh_runs():
    server._runs_reset()
    yield
    server._runs_reset()


def call(c, token, tool, args=None):
    r = c.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"},
               json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}})
    assert r.status_code == 200, r.text
    import json
    return json.loads(r.json()["result"]["content"][0]["text"])


def until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def blocking_find(monkeypatch):
    gate = threading.Event()

    def fake(step=None, progress=None, **kw):
        with activate(progress):  # as the real cores do with the reporter they are handed
            while not gate.wait(0.02):
                report("collecting", stage="detail")  # a run reports as it goes
        return {"failures": [], "new_above_threshold": [1, 2]}

    monkeypatch.setattr(find_cmd, "_find_core", fake)
    return gate


def test_over_http_a_run_starts_at_once_and_its_result_comes_from_job_result(tmp_path, blocking_find):
    token = pairing.redeem(tmp_path, pairing.new_code(tmp_path, "p"))[1]
    with TestClient(serve_http.build_app(home=tmp_path, web_dir=None, name="")) as c:
        started = call(c, token, "find_jobs")
        assert started["started"] is True and started["tool"] == "find_jobs" and started["started_at"]
        assert "already in progress" in call(c, token, "find_jobs")["error"]
        assert call(c, token, "job_result", {"tool": "find_jobs"})["running"] is True
        blocking_find.set()
        assert until(lambda: call(c, token, "job_result", {"tool": "find_jobs"})["running"] is False)
        done = call(c, token, "job_result", {"tool": "find_jobs"})
        assert done["result"]["new_above_threshold"] == [1, 2] and done["finished_at"]


def test_cancel_job_stops_a_run_and_frees_the_lock(tmp_path, blocking_find):
    token = pairing.redeem(tmp_path, pairing.new_code(tmp_path, "p"))[1]
    with TestClient(serve_http.build_app(home=tmp_path, web_dir=None, name="")) as c:
        call(c, token, "find_jobs")
        assert call(c, token, "cancel_job")["cancelling"] == "find_jobs"
        assert until(lambda: call(c, token, "job_result", {"tool": "find_jobs"})["running"] is False)
        assert call(c, token, "job_result", {"tool": "find_jobs"})["cancelled"] is True
        assert call(c, token, "find_jobs")["started"] is True  # a new run starts
        blocking_find.set()


def test_cancel_with_nothing_running_says_so(tmp_path):
    assert "nothing" in asyncio.run(server.cancel_job())["error"]


def test_job_result_before_any_run(tmp_path):
    assert asyncio.run(server.job_result("find_jobs")) == {"tool": "find_jobs", "running": False}
    assert "error" in asyncio.run(server.job_result("compile"))


def test_over_stdio_runs_still_block_and_are_remembered(monkeypatch):
    monkeypatch.setattr(find_cmd, "_find_core", lambda step=None, **kw: {"failures": [], "top": ["x"]})
    out = asyncio.run(server.find_jobs())
    assert out["top"] == ["x"]
    assert asyncio.run(server.job_result("find_jobs"))["result"]["top"] == ["x"]
