"""MCP tools take a local path only inside the data folder or the checkout (#441), unless the
desktop app started the server: its paths come from the user's own file dialogs."""

import pytest

from door.core import path_scope, workspace


@pytest.fixture
def roots(tmp_path, monkeypatch):
    home, repo = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "REPO_ROOT", repo)
    monkeypatch.delenv(path_scope.ENV, raising=False)
    return home, repo


def test_a_path_in_the_data_folder_or_the_checkout_passes(roots):
    home, repo = roots
    assert path_scope.check(str(home / "profile" / "cv.pdf")) == home / "profile" / "cv.pdf"
    assert path_scope.check(str(repo / "x.md")) == repo / "x.md"


def test_a_relative_path_is_read_from_the_data_folder(roots):
    home, _ = roots
    assert path_scope.check("profile/cv.pdf") == home / "profile" / "cv.pdf"


@pytest.mark.parametrize("path", ["~/.ssh/id_rsa", "/etc/passwd", "../outside.pdf"])
def test_a_path_outside_is_refused(roots, path):
    with pytest.raises(ValueError, match="outside"):
        path_scope.check(path)


def test_a_symlink_out_of_the_data_folder_is_refused(roots, tmp_path):
    home, _ = roots
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    (home / "link.txt").symlink_to(secret)
    with pytest.raises(ValueError, match="outside"):
        path_scope.check(str(home / "link.txt"))


def test_the_desktop_app_may_name_any_path(roots, monkeypatch):
    monkeypatch.setenv(path_scope.ENV, "1")
    assert path_scope.check("/etc/passwd") == path_scope.Path("/etc/passwd")
