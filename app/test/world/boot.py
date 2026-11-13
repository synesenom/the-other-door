"""Start the real door MCP server inside a test world: everything is door's own code except the
edges that would leave the computer, which answer from the world the test built.

The journeys (app/journeys/) point DOOR_PYTHON at a wrapper that runs this file instead of
`python -m door.mcp_server`; the install test (app/e2e-install/redirect.ts) has an installed app run it on its
bundled Python and door. No production code knows about it. What it replaces:

- the network: every socket to a host that is not this computer is refused, and `requests`
  answers from `world.json`'s `internet` (a URL -> page map) or fails as an offline host would;
- the job boards `search` reads: one module per board in `world.json`'s `boards`, returning
  those postings (the ads a run finds);
- `follow`'s feed detection and `collect`'s feeds: `world.json`'s `feeds` (company -> platform,
  entry, postings);
- Google Drive: a folder in the world plays the Drive account (`drive/`), and the real sync
  logic (pull, push, conflict) runs over it;
- the phone server: a pretend tunnel with a fixed address;
- faults: before every tool call `faults.json` is read again, so a test can make a named tool
  answer `{"error": ...}`, wait, or kill the server, at the moment it wants.

`claude` and `tectonic` are stand-ins first on PATH (claude.py, tectonic.py), so the model and
LaTeX boundaries are processes, as they are for real. Every tool call is logged to `calls.jsonl`.
"""

import asyncio
import functools
import inspect
import io
import json
import os
import shutil
import socket
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

WORLD = Path(sys.argv[1]).resolve()
REPO = Path(__file__).resolve().parents[3]
# The door it runs is the one the app put on PYTHONPATH: the checkout's src/, or an installed app's own
# bundled door (the install test, app/e2e-install/); the checkout's only when nothing is named.
if not os.environ.get("PYTHONPATH"):
    sys.path.insert(0, str(REPO / "src"))


def world() -> dict:
    return json.loads((WORLD / "world.json").read_text(encoding="utf-8"))


def faults() -> dict:
    try:
        return json.loads((WORLD / "faults.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def log_call(kind: str, **fields) -> None:
    with (WORLD / "calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "at": time.time(), **fields}, default=str) + "\n")


# --------------------------------------------------------------------------- the clock
# The world has a fixed "now" (world.json's `now`, the moment the server started), so dates on screen
# are the same on every run and a screenshot can be compared. Time still passes from there.
# `from datetime import datetime` anywhere after this gets the world's class; pydantic sees a datetime.
import datetime as _dt  # noqa: E402

_REAL_DT, _REAL_DATE = _dt.datetime, _dt.date
_SHIFT = _REAL_DT.fromisoformat(world()["now"]) - _REAL_DT.now(_dt.timezone.utc)


class _PassThrough(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, cls.__mro__[1])

    def __subclasscheck__(cls, sub):
        return issubclass(sub, cls.__mro__[1])


class _WorldDatetime(_REAL_DT, metaclass=_PassThrough):
    @classmethod
    def now(cls, tz=None):
        return _REAL_DT.now(tz) + _SHIFT

    @classmethod
    def utcnow(cls):
        return _REAL_DT.utcnow() + _SHIFT

    @classmethod
    def today(cls):
        return _REAL_DT.now() + _SHIFT

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        from pydantic_core import core_schema

        return core_schema.datetime_schema()


class _WorldDate(_REAL_DATE, metaclass=_PassThrough):
    @classmethod
    def today(cls):
        return (_REAL_DT.now() + _SHIFT).date()

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        from pydantic_core import core_schema

        return core_schema.date_schema()


_dt.datetime = _WorldDatetime
_dt.date = _WorldDate

# --------------------------------------------------------------------------- the network
_LOCAL = {"127.0.0.1", "::1", "localhost"}
_real_connect = socket.socket.connect


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in _LOCAL and not host.startswith("/"):
        raise ConnectionRefusedError(f"the test world has no internet: {host}")
    return _real_connect(self, address)


socket.socket.connect = _guarded_connect

import requests  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402
from requests.structures import CaseInsensitiveDict  # noqa: E402


class _Body(io.BytesIO):
    """A response body read as urllib3's is: `PoliteSession` reads a streamed body with `read1(n, decode_content=True)`."""

    def read(self, amt=None, decode_content=None, **_):
        return super().read(amt)

    def read1(self, amt=-1, decode_content=None, **_):
        return super().read1(amt)

    def stream(self, amt=65536, decode_content=None):
        while chunk := self.read(amt):
            yield chunk


def _fake_send(self, request, **kwargs):
    url = request.url
    page = world().get("internet", {}).get(url) or world().get("internet", {}).get(url.rstrip("/"))
    log_call("http", url=url, served=page is not None)
    if page is None:
        raise requests.ConnectionError(f"the test world has no page at {url}")
    response = requests.Response()
    response.status_code = page.get("status", 200)
    response.headers = CaseInsensitiveDict({"Content-Type": page.get("content_type", "text/html; charset=utf-8")})
    body = page.get("body", "")
    response.raw = _Body(body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8"))
    response.url = url
    response.request = request
    response.encoding = "utf-8"
    return response


HTTPAdapter.send = _fake_send

# --------------------------------------------------------------------------- door, with its edges replaced
from door.commands import companies as companies_cmd  # noqa: E402
from door.commands import prepare as prepare_cmd  # noqa: E402
from door.core import drive, phone, sites  # noqa: E402
from door.core.models import JobPosting  # noqa: E402
from door.scrapers import report  # noqa: E402


def _posting(raw: dict) -> dict:
    now = datetime.now(timezone.utc)
    return JobPosting(
        **{
            "scraped_at": now,
            "posted_at": now,
            "apply_type": "external",
            **{k: v for k, v in raw.items() if k in JobPosting.model_fields},
        }
    ).model_dump(mode="json")


def _board(site: str) -> types.ModuleType:
    def scrape(config: dict, known_ids=frozenset(), **kwargs) -> list[dict]:
        board = world().get("boards", {}).get(site, {})
        if board.get("fail"):
            from door.scrapers import record_error

            record_error(site, board["fail"])
            return []
        for keyword in config.get("search_keywords") or config.get("role_targets") or []:
            report(f"'{keyword}': {len(board.get('postings', []))} results", site=site)
        if not board.get("postings"):
            from door.scrapers import record_answered

            record_answered(site)   # the board's own "no hits" page: a quiet day, not a changed site
        return [_posting(p) for p in board.get("postings", []) if p.get("platform_id") not in known_ids]

    module = types.ModuleType(sites.SITES[site].module)
    module.scrape = scrape
    return module


for _site in world().get("boards", {}):
    sys.modules[sites.SITES[_site].module] = _board(_site)
sites.boards_for_location = lambda location: list(world().get("boards", {}))


def _classify(session, company: dict, followed, ctx=None):
    feed = world().get("feeds", {}).get(company["company"])
    if feed is None:
        return None
    return "suggestions", {
        "platform": feed["platform"],
        "entry": feed["entry"],
        "config_key": sites.SITES[feed["platform"]].config_key,
        "evidence": f"{feed['entry']} is a {feed['platform']} board",
    }


companies_cmd._session = lambda: None
companies_cmd._classify = _classify


def _feed(platform: str) -> types.ModuleType:
    key = sites.SITES[platform].config_key

    def scrape(config: dict, known_ids=frozenset(), **kwargs) -> list[dict]:
        by_entry = {f["entry"]: (name, f) for name, f in world().get("feeds", {}).items() if f["platform"] == platform}
        out = []
        for entry in config.get(key, []):
            entry = entry if isinstance(entry, str) else entry.get("slug") or entry.get("id") or ""
            if entry not in by_entry:
                continue
            _, feed = by_entry[entry]
            report(f"{entry}: {len(feed.get('postings', []))} jobs", site=platform)
            out += [_posting(p) for p in feed.get("postings", []) if p.get("platform_id") not in known_ids]
        return out

    module = types.ModuleType(sites.SITES[platform].module)
    module.scrape = scrape
    return module


for _platform in {f["platform"] for f in world().get("feeds", {}).values()}:
    sys.modules[sites.SITES[_platform].module] = _feed(_platform)

prepare_cmd._HEARTBEAT_INTERVAL_S = 1.0

# --------------------------------------------------------------------------- Google Drive: a folder plays the account
_DRIVE = WORLD / "drive"
_DRIVE.mkdir(exist_ok=True)
drive._BASE = WORLD / "config"
drive.is_configured = lambda: bool(world().get("drive", {}).get("configured", True))


def _drive_fail(what: str) -> None:
    said = faults().get("drive", {}).get(what)
    if said:
        raise drive.DriveError(said)


def _connect(open_browser=None, timeout: float = 300, show_url=None) -> dict:
    if not drive.is_configured():
        raise drive.DriveError(
            "Google Drive sync is not configured in this build: the maintainer has not set the "
            "OAuth client (CLIENT_ID / CLIENT_SECRET in src/door/core/drive.py)."
        )
    account = world().get("drive", {}).get("account", "someone@example.com")
    drive.write_state({"refresh_token": "world", "access_token": "world", "expires_at": time.time() + 3600})
    drive.update_state(account=account)
    return {"account": account}


def _remote_meta():
    archive = _DRIVE / "door-data.tar.gz"
    if not archive.exists():
        return None
    import hashlib

    return {"id": "world-archive", "version": hashlib.md5(archive.read_bytes()).hexdigest()}


def _download(dest: Path) -> None:
    if _remote_meta() is None:
        raise drive.DriveError("There is no archive of The other door on Google Drive.")
    shutil.copyfile(_DRIVE / "door-data.tar.gz", dest)


def _upload(src: Path) -> str:
    _drive_fail("upload")
    shutil.copyfile(src, _DRIVE / "door-data.tar.gz")
    return _remote_meta()["version"]


def _disconnect() -> bool:
    if drive.read_state() is None:
        return False
    drive.clear_state()
    return True


drive.connect = _connect
drive.remote_meta = _remote_meta
drive.download = _download
drive.upload = _upload
drive.disconnect = _disconnect

# --------------------------------------------------------------------------- the phone: a pretend tunnel
# The same shapes as door.core.phone: `address`, `lasting`, devices as {device, paired_at, last_seen}.
# A pairing waits for "the phone": the test writes `<world>/phone-scanned` and the next status pairs it.
_PHONE = {"running": False, "devices": [], "pending": None}
_ADDRESS = "https://quiet-river.trycloudflare.example"


def _phone_status(home, **deps) -> dict:
    scanned = WORLD / "phone-scanned"
    if _PHONE["pending"] and scanned.exists():
        scanned.unlink()
        name = _PHONE["pending"]
        _PHONE["devices"] = [d for d in _PHONE["devices"] if d["device"] != name]
        _PHONE["devices"].append({"device": name, "paired_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "last_seen": None})
        _PHONE["pending"] = None
    out = {"running": _PHONE["running"], "devices": list(_PHONE["devices"]), "web_built": True, "tailscale_installed": False}
    if _PHONE["running"]:
        out.update(connection=_PHONE["connection"], address=_ADDRESS, port=8765, lasting=_PHONE["connection"] == "tailscale")
    return out


def _phone_start(home, connection: str, **deps) -> dict:
    said = faults().get("phone", {}).get("start")
    if said:
        return said
    _PHONE.update(running=True, connection=connection)
    return _phone_status(home)


def _phone_stop(home, **deps) -> dict:
    was = _PHONE["running"]
    _PHONE["running"] = False
    return {"stopped": was}


def _phone_pair(home, device: str, **deps) -> dict:
    if not _PHONE["running"]:
        return {"error": "The other door is not serving a phone yet; start it first"}
    _PHONE["pending"] = device.strip()
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 29 29"><rect width="29" height="29" fill="#fff"/><path d="M1 1h7v7H1zM21 1h7v7h-7zM1 21h7v7H1z" fill="#000"/></svg>'
    expires = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=300)
    return {"device": device.strip(), "qr_svg": svg, "expires_at": expires.isoformat(timespec="seconds")}


def _phone_remove(home, device: str) -> dict:
    devices = _PHONE["devices"]
    if not any(d["device"] == device for d in devices):
        return {"error": f"no paired phone is called {device!r}"}
    _PHONE["devices"] = [d for d in devices if d["device"] != device]
    return {"removed": device}


phone.status = _phone_status
phone.start = _phone_start
phone.stop = _phone_stop
phone.pair = _phone_pair
phone.remove = _phone_remove

# --------------------------------------------------------------------------- the server, with faults and a call log
from door import mcp_server  # noqa: E402


def _fault_for(tool: str) -> dict | None:
    said = faults().get("tools", {}).get(tool)
    if not said:
        return None
    if said.get("once"):
        current = faults()
        current["tools"].pop(tool, None)
        (WORLD / "faults.json").write_text(json.dumps(current), encoding="utf-8")
    return said


def _answer_fault(said: dict):
    if said.get("crash"):
        os._exit(3)
    if "error" in said:
        return {"error": said["error"]}
    return None


def _with_faults(name: str, fn):
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            log_call("tool", tool=name, args={k: v for k, v in kwargs.items() if k != "ctx"})
            said = _fault_for(name)
            if said:
                await asyncio.sleep(said.get("delay_s", 0))
                answer = _answer_fault(said)
                if answer is not None:
                    return answer
            return await fn(*args, **kwargs)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        log_call("tool", tool=name, args=kwargs)
        said = _fault_for(name)
        if said:
            time.sleep(said.get("delay_s", 0))
            answer = _answer_fault(said)
            if answer is not None:
                return answer
        return fn(*args, **kwargs)

    return wrapper


for _name, _tool in mcp_server.mcp._tool_manager._tools.items():
    _tool.fn = _with_faults(_name, _tool.fn)

if __name__ == "__main__":
    mcp_server.main()
