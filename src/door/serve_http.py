"""`door serve`'s HTTP app (#302): the same MCP tools as stdio, for a paired phone.

Routes, for one data folder (`home`) each:

- `POST /mcp` — the MCP server (streamable HTTP, stateless, JSON answers), behind a device token.
- `POST /pair` — trade a one-time pairing code for a device token (`core/pairing.py`).
- `GET /files/jobs/output/...` — a prepared job's files (the page images), behind the token; nothing else.
- `POST /session` — (token) sets an HttpOnly cookie that opens `/files/` only, so an `<img>` can load a page.
- `GET /manifest.webmanifest` and the web app (`app/`'s web build, #303) — public: code, no data.

Every request to a guarded route needs `Authorization: Bearer <token>`. Wrong tokens and codes are
counted per client address (the tunnel's forwarded address only when the peer is this machine) and lock
that address out for a while. Answers carry `Cache-Control: no-store` and no server banner.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from door import mcp_server as server
from door import serve_policy
from door.core import pairing, workspace

MAX_BODY = 1_000_000         # a request's body, at most (a pasted ad is far less)
MAX_FAILURES = 10            # wrong tokens or codes from one address ...
FAILURE_WINDOW = 600.0       # ... within ten minutes ...
LOCKOUT = 900.0              # ... lock it out for fifteen
_TOUCH_EVERY = timedelta(minutes=5)
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_GUARDED = ("/mcp", "/files/", "/session")
_COOKIE = "door_files"
_SECURITY = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
# The phone app's page: its own code only (the desktop renderer's policy, with blob: images and a worker).
CSP = "; ".join([
    "default-src 'self'", "style-src 'self' 'unsafe-inline'", "script-src 'self'", "img-src 'self' data: blob:",
    "font-src 'self'", "connect-src 'self'", "manifest-src 'self'", "worker-src 'self'", "object-src 'none'",
    "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'",
])

_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>The other door</title>
<p>The other door is serving, but the phone app is not built yet. In the checkout: <code>cd app && npm run build:web</code>,
then start <code>./door serve</code> again.</p>"""


class _Limiter:
    """Failed attempts per address; an address with too many is refused until its lockout ends."""

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def locked(self, who: str) -> bool:
        with self._lock:
            return self._until.get(who, 0.0) > time.monotonic()

    def fail(self, who: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._fails.get(who, []) if now - t < FAILURE_WINDOW] + [now]
            self._fails[who] = recent
            if len(recent) >= MAX_FAILURES:
                self._until[who] = now + LOCKOUT
                self._fails[who] = []


def _client(scope: dict) -> str:
    peer = (scope.get("client") or ("?", 0))[0]
    if peer in _LOOPBACK:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        # Cloudflare sets CF-Connecting-IP itself; in X-Forwarded-For only the last entry is the proxy's
        # (the ones before it are whatever the client sent)
        forwarded = headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            return forwarded
    return peer


def _cookie(scope: dict, name: str) -> str:
    raw = dict(scope.get("headers", [])).get(b"cookie", b"").decode("latin-1")
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


async def _read_body(receive) -> bytes | None:
    """The whole request body, or None when it is larger than MAX_BODY."""
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
        if not message.get("more_body"):
            break
    return b"".join(chunks)


def _refused(message: dict) -> dict | None:
    """A JSON-RPC answer for a `tools/call` the phone may not make (serve_policy), or None."""
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return None
    params = message.get("params") or {}
    why = serve_policy.refusal(str(params.get("name", "")), params.get("arguments") or {})
    if why is None:
        return None
    text = json.dumps({"error": why})
    return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"content": [{"type": "text", "text": text}], "isError": False}}


def _theme() -> dict:
    """The manifest's colours: the design tokens' ground (the logo's parchment)."""
    try:
        tokens = json.loads((workspace.REPO_ROOT / "docs" / "design" / "tokens.json").read_text(encoding="utf-8"))
        return {"background_color": tokens["color"]["light"]["ground"]["value"], "theme_color": tokens["color"]["light"]["ground"]["value"]}
    except (OSError, ValueError, KeyError):
        return {"background_color": "#F1E6CF", "theme_color": "#F1E6CF"}


def manifest(name: str) -> dict:
    """The installable app's manifest: named for this instance, so two people's icons are told apart."""
    return {
        "name": f"The other door — {name}" if name else "The other door",
        "short_name": "The other door",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        **_theme(),
        "share_target": {"action": "/share", "method": "GET", "params": {"title": "title", "text": "text", "url": "url"}},
        "icons": [
            {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }


def build_app(*, home: Path, web_dir: Path | None, name: str):
    """The Starlette app for one data folder: FastMCP's streamable-HTTP app plus The other door's routes and guard."""
    home = Path(home).resolve()
    output = (home / "jobs" / "output").resolve()
    limiter = _Limiter()
    seen: dict[str, datetime] = {}

    # Stateless JSON answers: a phone that slept or changed networks just calls again. The host check
    # against DNS rebinding is off: a tunnel's hostname is not known here, and every call needs a token.
    server.mcp.settings.stateless_http = True
    server.mcp.settings.json_response = True
    server.mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    server.mcp._session_manager = None  # one per app: a session manager runs once
    server.enable_background_runs()  # a phone sleeps and a tunnel cuts long requests: runs return at once
    app = server.mcp.streamable_http_app()

    async def pair(request: Request) -> Response:
        try:
            body = await request.json()
            code = str(body.get("code", ""))
        except ValueError:
            code = ""
        got = pairing.redeem(home, code) if code else None
        if got is None:
            limiter.fail(_client(request.scope))
            return JSONResponse({"error": "That code is wrong or has expired; make a new one on the computer running The other door."}, status_code=401)
        device, token = got
        return JSONResponse({"device": device, "token": token})

    async def files(request: Request) -> Response:
        rel = request.path_params["path"]
        target = (home / rel).resolve()
        if not target.is_relative_to(output) or not target.is_file():
            return Response("Not found", status_code=404)
        return FileResponse(target)

    async def session(request: Request) -> Response:
        token = request.headers.get("authorization", "")[7:].strip()
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response = JSONResponse({"ok": True})
        response.set_cookie(_COOKIE, token, httponly=True, samesite="strict", path="/files", secure=secure, max_age=400 * 24 * 3600)
        return response

    async def manifest_route(request: Request) -> Response:
        return JSONResponse(manifest(name), media_type="application/manifest+json")

    async def web(request: Request) -> Response:
        if web_dir is None or not (Path(web_dir) / "index.html").is_file():
            return HTMLResponse(_NOT_BUILT)
        root = Path(web_dir).resolve()
        target = (root / request.path_params.get("path", "")).resolve()
        if target.is_relative_to(root) and target.is_file():
            return FileResponse(target)
        return FileResponse(root / "index.html")  # a screen's own address (a reload, a share) opens the app

    app.router.routes.extend([
        Route("/pair", pair, methods=["POST"]),
        Route("/session", session, methods=["POST"]),
        Route("/files/{path:path}", files, methods=["GET"]),
        Route("/manifest.webmanifest", manifest_route, methods=["GET"]),
        Route("/{path:path}", web, methods=["GET"]),
    ])

    inner = app.middleware_stack or app.build_middleware_stack()

    async def guard(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        path = scope.get("path", "")

        async def send_secured(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"server", b"cache-control")]
                headers += [(k.lower().encode(), v.encode()) for k, v in _SECURITY.items()]
                headers.append((b"content-security-policy", CSP.encode()))
                message = {**message, "headers": headers}
            await send(message)

        who = _client(scope)
        if path.startswith(_GUARDED) or path == "/pair":
            if limiter.locked(who):
                return await JSONResponse({"error": "Too many wrong attempts; try again later."}, status_code=429)(scope, receive, send_secured)
        if path.startswith(_GUARDED):
            auth = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
            token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
            if not token and path.startswith("/files/"):  # an <img>: the session cookie, for files only
                token = _cookie(scope, _COOKIE)
            device = pairing.verify(home, token)
            if device is None:
                limiter.fail(who)
                return await JSONResponse({"error": "This device is not paired with The other door."}, status_code=401)(scope, receive, send_secured)
            now = datetime.now(UTC)
            if now - seen.get(device, datetime.min.replace(tzinfo=UTC)) > _TOUCH_EVERY:
                seen[device] = now
                pairing.touch(home, device, now=now)
        if path == "/mcp" and scope.get("method") == "POST":
            # A phone is not a Claude Code session: only its own tools, no paths, no home-network addresses.
            body = await _read_body(receive)
            if body is None:
                return await JSONResponse({"error": "That request is too large."}, status_code=413)(scope, receive, send_secured)
            try:
                parsed = json.loads(body or b"null")
            except ValueError:
                parsed = None
            messages = parsed if isinstance(parsed, list) else [parsed]
            answers = [a for a in (_refused(m) for m in messages) if a is not None]
            if answers:
                return await JSONResponse(answers if isinstance(parsed, list) else answers[0])(scope, receive, send_secured)
            sent = False

            async def replay():
                nonlocal sent
                if sent:
                    return await receive()
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}

            return await inner(scope, replay, send_secured)
        return await inner(scope, receive, send_secured)

    app.middleware_stack = guard
    app.state.home = home
    return app
