"""The MCP tools that name a local file refuse one outside the data folder and the checkout (#441)."""

import pytest

import door.mcp_server as server
from door.commands import add as add_cmd
from door.commands import archive as archive_cmd
from door.commands import cv as cv_cmd
from door.commands import profile as profile_cmd
from door.core import path_scope, workspace


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.delenv(path_scope.ENV, raising=False)
    calls = []
    for mod, name in ((cv_cmd, "_draft_cv_core"), (add_cmd, "_add_core"), (archive_cmd, "_export_core"),
                      (archive_cmd, "_import_core"), (profile_cmd, "_init_core")):
        monkeypatch.setattr(mod, name, lambda *a, _n=name, **kw: calls.append((_n, a, kw)) or {"ok": True})
    return home, calls


@pytest.mark.parametrize("call", [
    lambda: server.draft_cv(["/root/.ssh/id_rsa"]),
    lambda: server.import_posting(path="/etc/passwd"),
    lambda: server.export_data(path="/tmp/elsewhere"),
    lambda: server.import_data("/tmp/elsewhere/door.tar.gz"),
    lambda: server.init_profile(other={"cv_content": "/root/.ssh/id_rsa"}),
    lambda: server.init_profile(other={"cv_template": "../../etc/x.tex"}),
])
def test_a_path_outside_is_refused_before_the_core_runs(scoped, call):
    _, calls = scoped
    result = call()
    assert "outside the data folder" in result["error"]
    assert calls == []


def test_paths_inside_and_urls_pass(scoped):
    home, calls = scoped
    assert server.draft_cv([str(home / "cv.pdf"), "https://me.example"]) == {"ok": True}
    assert server.import_posting(path=str(home / "ad.txt")) == {"ok": True}
    assert server.export_data() == {"ok": True}
    assert server.init_profile(other={"cv_template": "profile/cv.template.tex"}) == {"ok": True}
    assert len(calls) == 4


def test_the_desktop_app_names_any_path(scoped, monkeypatch):
    _, calls = scoped
    monkeypatch.setenv(path_scope.ENV, "1")
    assert server.import_data("/tmp/elsewhere/door.tar.gz") == {"ok": True}
