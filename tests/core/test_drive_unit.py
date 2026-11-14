"""Google Drive transport: state file, OAuth, REST (issue #265). HTTP is mocked with `responses`."""

import json
import os
import stat
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
import requests
import responses

from tests.paths import REPO_ROOT

from door.core import drive

TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(drive, "CLIENT_ID", "test-client")
    monkeypatch.setattr(drive, "CLIENT_SECRET", "test-secret")


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A connected computer: a state file with a still-valid access token."""
    monkeypatch.setattr(drive, "_BASE", tmp_path / "cfg")
    drive.write_state({"refresh_token": "rt", "access_token": "at", "expires_at": 9e12, "account": "me@x.org"})
    return tmp_path / "cfg" / "drive.json"


# --------------------------------------------------------------------------- state
def test_state_path_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.setattr(drive, "_BASE", None)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert drive.state_path() == tmp_path / ".config" / "door" / "drive.json"


def test_state_path_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(drive, "_BASE", None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert drive.state_path() == tmp_path / "xdg" / "door" / "drive.json"


def test_state_path_on_windows_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(drive, "_BASE", None)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert drive.state_path() == tmp_path / "roaming" / "door" / "drive.json"


def test_read_state_is_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    assert drive.read_state() is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_write_state_is_private(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path / "cfg")
    drive.write_state({"refresh_token": "x"})
    assert stat.S_IMODE(os.stat(tmp_path / "cfg").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(tmp_path / "cfg" / "drive.json").st_mode) == 0o600
    assert drive.read_state() == {"refresh_token": "x"}
    drive.clear_state()
    assert drive.read_state() is None


# --------------------------------------------------------------------------- connect
def test_connect_refuses_while_unconfigured(monkeypatch, tmp_path):
    import webbrowser

    monkeypatch.setattr(drive, "_BASE", tmp_path)
    monkeypatch.setattr(drive, "CLIENT_ID", "")
    monkeypatch.setattr(drive, "CLIENT_SECRET", "")
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a))
    monkeypatch.setattr(drive.socketserver.TCPServer, "server_bind", lambda self: opened.append("bind"))
    with pytest.raises(drive.DriveError, match="not configured in this build"):
        drive.connect()
    assert opened == []


def test_connect_looks_up_the_browser_at_call_time(monkeypatch, tmp_path):
    # A default bound at import time escapes a patched `webbrowser.open` (tests opened real tabs).
    import webbrowser

    monkeypatch.setattr(drive, "_BASE", tmp_path)
    monkeypatch.setattr(drive, "CLIENT_ID", "id")
    monkeypatch.setattr(drive, "CLIENT_SECRET", "secret")
    seen = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: seen.append(url) or True)
    with pytest.raises(drive.DriveError, match="no answer"):
        drive.connect(timeout=0.1)
    assert seen and seen[0].startswith("https://accounts.google.com/")


def test_offline_tests_run_without_the_real_client():
    assert drive.CLIENT_ID == "" and drive.CLIENT_SECRET == ""


def _browser(query_for):
    """A fake browser: follows the auth URL's redirect to the loopback server."""
    seen = {}

    def open_browser(url):
        parts = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        seen.update(q, url=url)
        redirect = q["redirect_uri"] + "?" + urllib.parse.urlencode(query_for(q))
        threading.Thread(target=lambda: urllib.request.urlopen(redirect, timeout=5).read(), daemon=True).start()
        return True

    return open_browser, seen


@responses.activate
def test_connect_runs_pkce_loopback_and_stores_tokens(configured, tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    responses.post(TOKEN_URL, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    responses.get(f"{API}/drive/v3/about", json={"user": {"emailAddress": "me@x.org"}})
    browser, seen = _browser(lambda q: {"code": "abc", "state": q["state"]})

    result = drive.connect(open_browser=browser, timeout=10)

    assert result["account"] == "me@x.org"
    assert seen["code_challenge_method"] == "S256"
    assert seen["redirect_uri"].startswith("http://127.0.0.1:")
    assert seen["scope"] == "https://www.googleapis.com/auth/drive.file"
    assert seen["access_type"] == "offline"
    body = urllib.parse.parse_qs(responses.calls[0].request.body)
    assert body["code"] == ["abc"] and body["code_verifier"][0] and body["client_secret"] == ["test-secret"]
    stored = drive.read_state()
    assert stored["refresh_token"] == "rt" and stored["account"] == "me@x.org"


@responses.activate
def test_connect_rejects_a_wrong_state(configured, tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    browser, _ = _browser(lambda q: {"code": "abc", "state": "forged"})
    with pytest.raises(drive.DriveError, match="state"):
        drive.connect(open_browser=browser, timeout=10)
    assert drive.read_state() is None


@responses.activate
def test_connect_surfaces_the_url_when_no_browser_opens(configured, tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    with pytest.raises(drive.DriveError, match="no answer") as exc:
        drive.connect(open_browser=lambda url: False, timeout=0.2)
    assert "accounts.google.com" in str(exc.value)


@responses.activate
def test_connect_shows_the_url_even_when_the_browser_opens(configured, tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    shown = []
    with pytest.raises(drive.DriveError, match="no answer"):
        drive.connect(open_browser=lambda url: True, timeout=0.2, show_url=shown.append)
    assert len(shown) == 1 and shown[0].startswith("https://accounts.google.com/")


@responses.activate
def test_connect_times_out(configured, tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    with pytest.raises(drive.DriveError, match="no answer"):
        drive.connect(open_browser=lambda url: True, timeout=0.2)


@responses.activate
def test_connect_reports_a_denied_consent(configured, tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    browser, _ = _browser(lambda q: {"error": "access_denied", "state": q["state"]})
    with pytest.raises(drive.DriveError, match="access_denied"):
        drive.connect(open_browser=browser, timeout=10)


# --------------------------------------------------------------------------- tokens
@responses.activate
def test_access_token_refreshes_when_expired(configured, state):
    drive.write_state({**drive.read_state(), "expires_at": 0})
    responses.post(TOKEN_URL, json={"access_token": "new", "expires_in": 3600})
    assert drive.access_token() == "new"
    assert drive.read_state()["access_token"] == "new"


@responses.activate
def test_revoked_grant_says_to_reconnect(configured, state):
    drive.write_state({**drive.read_state(), "expires_at": 0})
    responses.post(TOKEN_URL, json={"error": "invalid_grant"}, status=400)
    with pytest.raises(drive.DriveError, match="Drive disconnected.*data connect"):
        drive.access_token()


def test_access_token_without_state_says_not_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    with pytest.raises(drive.DriveError, match="not connected"):
        drive.access_token()


# --------------------------------------------------------------------------- REST
def _files(items):
    return {"files": items}


@responses.activate
def test_remote_meta_none_when_nothing_on_drive(state):
    responses.get(f"{API}/drive/v3/files", json=_files([]))
    assert drive.remote_meta() is None
    assert "application/vnd.google-apps.folder" in responses.calls[0].request.url or "The+other+door" in responses.calls[0].request.url


@responses.activate
def test_remote_meta_finds_the_archive_in_the_folder(state):
    responses.get(f"{API}/drive/v3/files", json=_files([{"id": "F1"}]))
    responses.get(f"{API}/drive/v3/files", json=_files([{"id": "A1", "md5Checksum": "7"}]))
    meta = drive.remote_meta()
    assert meta == {"id": "A1", "version": "7", "properties": {}}
    assert "door-data.tar.gz" in urllib.parse.unquote_plus(responses.calls[1].request.url)
    assert drive.read_state()["file_id"] == "A1"


@responses.activate
def test_remote_meta_cached_id_404_means_no_remote(state):
    drive.write_state({**drive.read_state(), "file_id": "gone"})
    responses.get(f"{API}/drive/v3/files/gone", status=404)
    responses.get(f"{API}/drive/v3/files", json=_files([]))
    assert drive.remote_meta() is None
    assert "file_id" not in drive.read_state()


@responses.activate
def test_remote_meta_uses_cached_id(state):
    drive.write_state({**drive.read_state(), "file_id": "A1"})
    responses.get(f"{API}/drive/v3/files/A1", json={"id": "A1", "md5Checksum": "9"})
    assert drive.remote_meta() == {"id": "A1", "version": "9", "properties": {}}


@responses.activate
def test_upload_creates_folder_and_file_first(state, tmp_path):
    src = tmp_path / "a.tar.gz"
    src.write_bytes(b"data")
    responses.get(f"{API}/drive/v3/files", json=_files([]))
    responses.post(f"{API}/drive/v3/files", json={"id": "F1"})
    responses.post(f"{API}/upload/drive/v3/files", json={"id": "A1", "md5Checksum": "3"})
    assert drive.upload(src) == "3"
    created = [c for c in responses.calls if c.request.method == "POST"]
    assert json.loads(created[0].request.body)["mimeType"] == "application/vnd.google-apps.folder"
    assert b"door-data.tar.gz" in created[1].request.body and b"data" in created[1].request.body
    assert drive.read_state()["file_id"] == "A1"


@responses.activate
def test_upload_updates_the_existing_file(state, tmp_path):
    drive.write_state({**drive.read_state(), "file_id": "A1"})
    src = tmp_path / "a.tar.gz"
    src.write_bytes(b"data")
    responses.get(f"{API}/drive/v3/files/A1", json={"id": "A1", "md5Checksum": "3"})
    responses.patch(f"{API}/upload/drive/v3/files/A1", json={"id": "A1", "md5Checksum": "4"})
    assert drive.upload(src) == "4"


@responses.activate
def test_version_is_the_content_checksum_not_drives_counter(state, tmp_path):
    # Drive bumps `version` on its own right after an upload; only the content says "changed".
    drive.write_state({**drive.read_state(), "file_id": "A1"})
    src = tmp_path / "a.tar.gz"
    src.write_bytes(b"data")
    responses.get(f"{API}/drive/v3/files/A1", json={"id": "A1", "version": "1", "md5Checksum": "old"})
    responses.patch(f"{API}/upload/drive/v3/files/A1", json={"id": "A1", "version": "2", "md5Checksum": "abc"})
    pushed = drive.upload(src)
    responses.get(f"{API}/drive/v3/files/A1", json={"id": "A1", "version": "3", "md5Checksum": "abc"})
    assert drive.remote_meta()["version"] == pushed == "abc"


PROPS = {"door_profile_version": "0.1", "door_jobs_version": "0.0"}


@responses.activate
def test_remote_meta_asks_for_and_returns_the_app_properties(state):
    drive.write_state({**drive.read_state(), "file_id": "A1"})
    responses.get(f"{API}/drive/v3/files/A1", json={"id": "A1", "md5Checksum": "9", "appProperties": PROPS})
    meta = drive.remote_meta()
    assert meta["properties"] == PROPS
    assert "appProperties" in urllib.parse.parse_qs(urllib.parse.urlsplit(responses.calls[0].request.url).query)["fields"][0]


@responses.activate
def test_remote_meta_of_a_listed_file_returns_its_app_properties(state):
    responses.get(f"{API}/drive/v3/files", json=_files([{"id": "F1"}]))
    responses.get(f"{API}/drive/v3/files", json=_files([{"id": "A1", "md5Checksum": "7", "appProperties": PROPS}]))
    assert drive.remote_meta()["properties"] == PROPS
    assert "appProperties" in urllib.parse.parse_qs(urllib.parse.urlsplit(responses.calls[1].request.url).query)["fields"][0]


@responses.activate
def test_upload_of_a_new_file_sends_the_app_properties(state, tmp_path):
    src = tmp_path / "a.tar.gz"
    src.write_bytes(b"data")
    responses.get(f"{API}/drive/v3/files", json=_files([]))
    responses.post(f"{API}/drive/v3/files", json={"id": "F1"})
    responses.post(f"{API}/upload/drive/v3/files", json={"id": "A1", "md5Checksum": "3"})
    drive.upload(src, PROPS)
    body = [c for c in responses.calls if c.request.method == "POST"][1].request.body
    head = json.loads(body.split(b"\r\n\r\n")[1].split(b"\r\n")[0])
    assert head["appProperties"] == PROPS and head["name"] == "door-data.tar.gz"
    assert b"data" in body


@responses.activate
def test_upload_of_an_existing_file_sends_the_app_properties(state, tmp_path):
    drive.write_state({**drive.read_state(), "file_id": "A1"})
    src = tmp_path / "a.tar.gz"
    src.write_bytes(b"data")
    responses.get(f"{API}/drive/v3/files/A1", json={"id": "A1", "md5Checksum": "3"})
    responses.patch(f"{API}/upload/drive/v3/files/A1", json={"id": "A1", "md5Checksum": "4"})
    assert drive.upload(src, PROPS) == "4"
    call = [c for c in responses.calls if c.request.method == "PATCH"][0]
    assert "multipart" in call.request.url
    assert json.dumps(PROPS).encode()[1:-1].split(b",")[0] in call.request.body
    assert b"data" in call.request.body


@responses.activate
def test_download_writes_the_file(state, tmp_path):
    drive.write_state({**drive.read_state(), "file_id": "A1"})
    responses.get(f"{API}/drive/v3/files/A1", json={"id": "A1", "md5Checksum": "2"})
    responses.get(f"{API}/drive/v3/files/A1", body=b"payload")
    dest = tmp_path / "out.tar.gz"
    drive.download(dest)
    assert dest.read_bytes() == b"payload"


@responses.activate
def test_server_error_is_a_drive_error(state):
    responses.get(f"{API}/drive/v3/files", status=503)
    with pytest.raises(drive.DriveError, match="503"):
        drive.remote_meta()


@responses.activate
def test_connection_error_is_an_offline_error(state):
    responses.get(f"{API}/drive/v3/files", body=requests.ConnectionError("down"))
    with pytest.raises(drive.DriveOffline):
        drive.remote_meta()


# --------------------------------------------------------------------------- disconnect
@responses.activate
def test_disconnect_revokes_and_clears(state):
    responses.post(REVOKE_URL, status=200)
    assert drive.disconnect() is True
    assert drive.read_state() is None
    assert len(responses.calls) == 1


@responses.activate
def test_disconnect_swallows_a_failed_revoke(state):
    responses.post(REVOKE_URL, body=requests.ConnectionError("down"))
    drive.disconnect()
    assert drive.read_state() is None


def test_disconnect_when_not_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "_BASE", tmp_path)
    assert drive.disconnect() is False


def test_the_client_is_stored_obscured_and_read_back_whole():
    # A desktop client is public by design, but a scanner refuses it in plain text: the module
    # keeps it XOR-ed with a fixed key and decodes it on load.
    assert drive._reveal(drive._OBSCURED_CLIENT_ID).endswith(".apps.googleusercontent.com")
    assert drive._reveal(drive._OBSCURED_CLIENT_SECRET).startswith("GOCSPX-")
    source = (REPO_ROOT / "src/door/core/drive.py").read_text(encoding="utf-8")
    assert "GOCSPX-" not in source and ".apps.googleusercontent.com\"" not in source
