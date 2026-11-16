"""A small Chrome DevTools Protocol client over a plain RFC 6455 websocket (#165).

Standard library only: the print path needs no Node and no extra package. Single-threaded: the
replies and events are read inside `send` and `wait_event`; an event handler may itself `send`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
from urllib.parse import urlsplit

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CdpError(Exception):
    """The browser answered a command with an error, or the connection broke."""


class CdpTimeout(CdpError):
    """A reply or event did not come in time."""


class Cdp:
    def __init__(self, sock: socket.socket, leftover: bytes = b""):
        self._sock = sock
        self._buf = leftover
        self._next_id = 0
        self._replies: dict[int, dict] = {}
        self._events: list[dict] = []
        self._handlers: dict[str, list] = {}

    @classmethod
    def connect(cls, ws_url: str, timeout: float = 10.0) -> "Cdp":
        parts = urlsplit(ws_url)
        sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        sock.sendall((
            f"GET {path or '/'} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    raise CdpError("the browser closed the connection during the handshake")
                data += chunk
        except socket.timeout as exc:
            sock.close()
            raise CdpTimeout("the browser did not answer the websocket handshake") from exc
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        if " 101 " not in lines[0] or headers.get("sec-websocket-accept") != accept:
            sock.close()
            raise CdpError(f"websocket handshake refused: {lines[0]}")
        return cls(sock, rest)

    def on(self, event: str, handler) -> None:
        """Call `handler(params, session_id)` for each `event` as it is read."""
        self._handlers.setdefault(event, []).append(handler)

    def send(self, method: str, params: dict | None = None, *, session_id: str | None = None, timeout: float = 30.0) -> dict:
        self._next_id += 1
        mid = self._next_id
        message = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._write(json.dumps(message).encode())
        deadline = time.monotonic() + timeout
        while mid not in self._replies:
            self._pump(deadline, f"the reply to {method}")
        reply = self._replies.pop(mid)
        if "error" in reply:
            raise CdpError(f"{method}: {reply['error'].get('message', reply['error'])}")
        return reply.get("result", {})

    def wait_event(self, name: str, timeout: float = 30.0) -> dict:
        """The params of the next `name` event (events read earlier are kept for it)."""
        deadline = time.monotonic() + timeout
        while True:
            for i, event in enumerate(self._events):
                if event["method"] == name:
                    del self._events[i]
                    return event.get("params", {})
            self._pump(deadline, f"the {name} event")

    def close(self) -> None:
        try:
            self._write(b"", opcode=0x8)
        except OSError:
            pass
        self._sock.close()

    # --- frames ----------------------------------------------------------- #

    def _write(self, payload: bytes, opcode: int = 0x1) -> None:
        mask = os.urandom(4)
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload)) if n < 4096 else _mask_big(payload, mask)
        self._sock.sendall(head + mask + masked)

    def _read_exact(self, n: int, deadline: float, what: str) -> bytes:
        while len(self._buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                raise CdpTimeout(f"timed out waiting for {what}")
            self._sock.settimeout(left)
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout as exc:
                raise CdpTimeout(f"timed out waiting for {what}") from exc
            except OSError as exc:
                raise CdpError(f"the browser connection broke: {exc}") from exc
            if not chunk:
                raise CdpError("the browser closed the connection")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _frame(self, deadline: float, what: str) -> tuple[int, bool, bytes]:
        b0, b1 = self._read_exact(2, deadline, what)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read_exact(2, deadline, what))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read_exact(8, deadline, what))[0]
        mask = self._read_exact(4, deadline, what) if b1 & 0x80 else None
        payload = self._read_exact(n, deadline, what)
        if mask:
            payload = _mask_big(payload, mask)
        return b0 & 0x0F, bool(b0 & 0x80), payload

    def _pump(self, deadline: float, what: str) -> None:
        """Read one whole message (joining fragments, answering pings) and file it."""
        parts: list[bytes] = []
        while True:
            opcode, fin, payload = self._frame(deadline, what)
            if opcode == 0x9:
                self._write(payload, opcode=0xA)
            elif opcode == 0xA:
                continue
            elif opcode == 0x8:
                raise CdpError("the browser closed the connection")
            else:
                parts.append(payload)
                if fin:
                    break
        message = json.loads(b"".join(parts).decode("utf-8"))
        if "id" in message:
            self._replies[message["id"]] = message
            return
        handlers = self._handlers.get(message.get("method", ""), [])
        if handlers:
            for handler in handlers:
                handler(message.get("params", {}), message.get("sessionId"))
        else:
            self._events.append(message)


def _mask_big(payload: bytes, mask: bytes) -> bytes:
    key = (mask * (len(payload) // 4 + 1))[: len(payload)]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(key, "big")).to_bytes(len(payload), "big") if payload else b""
