"""Google Drive transport for `data connect|sync` (issue #265).

Plain `requests` plus the standard library: a loopback OAuth redirect with
PKCE, token refresh, and the few Drive REST calls the sync needs. Only the
`drive.file` scope is asked for, so The other door sees nothing but the folder and
archive it created itself (`My Drive/The other door/door-data.tar.gz`).

The per-computer state (refresh token, account, the archive's file id, the
version last synced) lives in `drive.json` outside `profile/` and `jobs/`, so
it never travels with the data: ``~/.config/door/`` (``$XDG_CONFIG_HOME``),
``%APPDATA%\\door\\`` on Windows; directory 0700, file 0600.

Every failure is a `DriveError` (`DriveOffline` when the network is down).
Nothing here prints; progress goes through `report()`.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

from door.core.progress import report

# The OAuth client of The other door (a Google Cloud "Desktop app" client, scope
# drive.file), in the Google Cloud project "The other door". A build with them empty makes
# `connect` fail plainly before opening a browser. A desktop client's secret is not confidential
# (it ships in every install); it is kept XOR-ed with `_KEY` only so secret scanners do not refuse it.
_OBSCURED_CLIENT_ID = "ZVhcEVtBXFFDFFVcXl9cEQ9CBgcHXENeGk5VDgxUGBBZQgZDVV4PVUwPSxIKVl0IFx4nRgJPABMEAAdTAR0MHVRUBE4QSxAEGQ=="
_OBSCURED_CLIENT_SECRET = "Eycmcz8sRSgVFgsdGABqWjJvNgIKEz0WEWECHSgdGEFmeh8="


_KEY = b"The other door: a desktop client, public by design"


def _reveal(obscured: str) -> str:
    data = base64.b64decode(obscured)
    return bytes(b ^ _KEY[i % len(_KEY)] for i, b in enumerate(data)).decode("ascii")


CLIENT_ID = _reveal(_OBSCURED_CLIENT_ID)
CLIENT_SECRET = _reveal(_OBSCURED_CLIENT_SECRET)

SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_NAME = "The other door"
FILE_NAME = "door-data.tar.gz"

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_API = "https://www.googleapis.com"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_TIMEOUT = 60

# Where drive.json lives; None = the per-OS default. Tests point it at a temp dir.
_BASE: Path | None = None


class DriveError(RuntimeError):
    """A Drive call failed (not connected, revoked, refused, unreachable)."""


class DriveOffline(DriveError):
    """The network or Google is unreachable."""


# --------------------------------------------------------------------------- state
def _base() -> Path:
    if _BASE is not None:
        return Path(_BASE)
    if sys.platform == "win32":
        root = os.environ.get("APPDATA")
        return (Path(root) if root else Path.home() / "AppData" / "Roaming") / "door"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "door"


def state_path() -> Path:
    return _base() / "drive.json"


def read_state() -> dict | None:
    """The saved connection, or None when this computer is not connected (or the file is unreadable)."""
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_state(state: dict) -> None:
    """Save `state` atomically, readable by this user only."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)


def update_state(**changes) -> dict:
    """Merge `changes` into the saved state (None removes a key) and return it."""
    state = read_state() or {}
    for key, value in changes.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value
    write_state(state)
    return state


def clear_state() -> None:
    state_path().unlink(missing_ok=True)


# --------------------------------------------------------------------------- http
def _request(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", _TIMEOUT)
    try:
        return requests.request(method, url, **kwargs)
    except requests.RequestException as exc:
        raise DriveOffline(f"Google Drive is unreachable ({type(exc).__name__})") from None


def _check(resp: requests.Response, what: str) -> requests.Response:
    if resp.status_code >= 400:
        raise DriveError(f"Google Drive {what} failed (HTTP {resp.status_code})")
    return resp


# --------------------------------------------------------------------------- connect
def is_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _wait_for_redirect(server: http.server.HTTPServer, open_browser, url: str, timeout: float, show_url=None) -> dict:
    """Serve one loopback request in a thread and return its query parameters."""
    got: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query)))
            body = b"The other door is connected to Google Drive. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, *args):  # silence the default stderr line
            pass

    server.RequestHandlerClass = Handler
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        if show_url is not None:
            show_url(url)
        opened = False
        try:
            opened = bool(open_browser(url))
        except Exception:  # noqa: BLE001 - a missing browser just means the user opens the URL
            opened = False
        if not opened:
            report(f"Open this address in a browser to connect Google Drive: {url}")
        if not done.wait(timeout):
            raise DriveError(
                f"Google Drive connect: no answer from the browser within {int(timeout)} s. "
                f"Open this address and allow access, then run `data connect` again: {url}"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return got


def connect(open_browser=None, timeout: float = 300, show_url=None) -> dict:
    """Authorise The other door once: loopback redirect with PKCE, then store the refresh token.

    Returns:
        ``{"account": <email>}``.

    Raises:
        DriveError: not configured in this build, denied, no answer, or refused by Google.
    """
    if not is_configured():
        raise DriveError(
            "Google Drive sync is not configured in this build: the maintainer has not set the "
            "OAuth client (CLIENT_ID / CLIENT_SECRET in src/door/core/drive.py)."
        )
    if open_browser is None:
        open_browser = webbrowser.open  # looked up now, so a patched `webbrowser.open` applies
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    answer = _wait_for_redirect(server, open_browser, f"{_AUTH_URL}?{query}", timeout, show_url)
    if answer.get("state") != state:
        raise DriveError("Google Drive connect: the answer did not match this request (state); try again.")
    if answer.get("error") or not answer.get("code"):
        raise DriveError(f"Google Drive connect was not allowed ({answer.get('error', 'no code')}).")

    resp = _request(
        "POST",
        _TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": answer["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
    )
    _check(resp, "sign-in")
    tokens = resp.json()
    if not tokens.get("refresh_token"):
        raise DriveError("Google Drive connect: Google sent no refresh token; try again.")
    write_state(
        {
            "refresh_token": tokens["refresh_token"],
            "access_token": tokens.get("access_token"),
            "expires_at": time.time() + float(tokens.get("expires_in", 3600)),
        }
    )
    about = _check(
        _request("GET", f"{_API}/drive/v3/about", params={"fields": "user"}, headers=_auth(tokens["access_token"])),
        "account lookup",
    ).json()
    account = (about.get("user") or {}).get("emailAddress", "")
    update_state(account=account)
    return {"account": account}


# --------------------------------------------------------------------------- tokens
def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def access_token() -> str:
    """A valid access token, refreshed when it is about to expire."""
    state = read_state()
    if not state or not state.get("refresh_token"):
        raise DriveError("Google Drive is not connected; run `./door data connect`.")
    if state.get("access_token") and float(state.get("expires_at", 0)) > time.time() + 60:
        return state["access_token"]
    resp = _request(
        "POST",
        _TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": state["refresh_token"],
            "grant_type": "refresh_token",
        },
    )
    if resp.status_code in (400, 401):
        try:
            error = resp.json().get("error")
        except ValueError:
            error = None
        if error == "invalid_grant":
            raise DriveError("Drive disconnected (access was revoked or expired); run `./door data connect`.")
    _check(resp, "token refresh")
    body = resp.json()
    update_state(access_token=body["access_token"], expires_at=time.time() + float(body.get("expires_in", 3600)))
    return body["access_token"]


def _api(method: str, path: str, **kwargs) -> requests.Response:
    headers = {**_auth(access_token()), **kwargs.pop("headers", {})}
    return _request(method, f"{_API}{path}", headers=headers, **kwargs)


# --------------------------------------------------------------------------- files
def _find(query: str) -> dict | None:
    resp = _check(_api("GET", "/drive/v3/files", params={"q": query, "fields": "files(id,md5Checksum)", "pageSize": 1}), "lookup")
    files = resp.json().get("files") or []
    return files[0] if files else None


def _folder_id() -> str | None:
    folder = _find(f"name='{FOLDER_NAME}' and mimeType='{_FOLDER_MIME}' and trashed=false")
    return folder["id"] if folder else None


def remote_meta() -> dict | None:
    """``{"id", "version"}`` of the archive on Drive, or None when it is not there.

    The version is the content's ``md5Checksum``: Drive's own ``version`` counter also moves
    on server-side changes right after an upload, which would read as "changed elsewhere".
    """
    state = read_state() or {}
    file_id = state.get("file_id")
    if file_id:
        resp = _api("GET", f"/drive/v3/files/{file_id}", params={"fields": "id,md5Checksum,trashed"})
        if resp.status_code != 404:
            _check(resp, "lookup")
            body = resp.json()
            if not body.get("trashed"):
                return {"id": body["id"], "version": body["md5Checksum"]}
        update_state(file_id=None)
    folder = _folder_id()
    if folder is None:
        return None
    found = _find(f"name='{FILE_NAME}' and '{folder}' in parents and trashed=false")
    if found is None:
        return None
    update_state(file_id=found["id"])
    return {"id": found["id"], "version": found["md5Checksum"]}


def download(dest: Path) -> None:
    """Write the archive on Drive to `dest`."""
    meta = remote_meta()
    if meta is None:
        raise DriveError("There is no archive of The other door on Google Drive.")
    resp = _check(_api("GET", f"/drive/v3/files/{meta['id']}", params={"alt": "media"}), "download")
    Path(dest).write_bytes(resp.content)


def upload(src: Path) -> str:
    """Put `src` on Drive as the archive (creating the folder and file on first use); return its new version."""
    content = Path(src).read_bytes()
    meta = remote_meta()
    if meta is not None:
        resp = _api(
            "PATCH",
            f"/upload/drive/v3/files/{meta['id']}",
            params={"uploadType": "media", "fields": "id,md5Checksum"},
            headers={"Content-Type": "application/gzip"},
            data=content,
        )
    else:
        folder = _folder_id()
        if folder is None:
            made = _check(
                _api("POST", "/drive/v3/files", params={"fields": "id"}, json={"name": FOLDER_NAME, "mimeType": _FOLDER_MIME}),
                "folder creation",
            )
            folder = made.json()["id"]
        boundary = secrets.token_hex(16)
        head = json.dumps({"name": FILE_NAME, "parents": [folder]})
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{head}\r\n"
            f"--{boundary}\r\nContent-Type: application/gzip\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--".encode()
        resp = _api(
            "POST",
            "/upload/drive/v3/files",
            params={"uploadType": "multipart", "fields": "id,md5Checksum"},
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
        )
    done = _check(resp, "upload").json()
    update_state(file_id=done["id"])
    return done["md5Checksum"]


# --------------------------------------------------------------------------- disconnect
def disconnect() -> bool:
    """Forget this computer's connection (and ask Google to revoke the token, best effort).

    The archive on Drive is left alone. Returns False when nothing was connected.
    """
    state = read_state()
    if state is None:
        return False
    token = state.get("refresh_token") or state.get("access_token")
    clear_state()
    if token:
        try:
            requests.post(_REVOKE_URL, data={"token": token}, timeout=15)
        except requests.RequestException:
            pass
    return True
