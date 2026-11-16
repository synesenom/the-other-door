"""A fake RFC 6455 server on loopback for the CDP tests (#165): one connection, scripted by a handler."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class Conn:
    """The server side of one websocket: read masked client frames, write unmasked ones."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = b""
        self.masked_ok = True

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def read_message(self):
        """(opcode, payload) of the next client frame; asserts it is masked."""
        b0, b1 = self._need(2)
        if not b1 & 0x80:
            self.masked_ok = False
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._need(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._need(8))[0]
        mask = self._need(4)
        data = bytearray(self._need(n))
        for i in range(n):
            data[i] ^= mask[i % 4]
        return b0 & 0x0F, bytes(data)

    def read_json(self):
        while True:
            opcode, data = self.read_message()
            if opcode == 0x1:
                return json.loads(data)
            if opcode == 0x8:
                raise EOFError

    def write(self, payload: bytes, opcode=0x1, fin=True, length_form=None):
        n = len(payload)
        form = length_form or ("7" if n < 126 else "16" if n < 1 << 16 else "64")
        head = bytes([(0x80 if fin else 0) | opcode])
        if form == "7":
            head += bytes([n])
        elif form == "16":
            head += bytes([126]) + struct.pack(">H", n)
        else:
            head += bytes([127]) + struct.pack(">Q", n)
        self.sock.sendall(head + payload)

    def send_json(self, obj, **kw):
        self.write(json.dumps(obj).encode(), **kw)


class FakeWs:
    """Listens on 127.0.0.1; `script(conn)` runs on the accepted connection in a thread."""

    def __init__(self, script):
        self.script = script
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.error = None
        self.conn = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/devtools/page/X"

    def _run(self):
        try:
            sock, _ = self.server.accept()
            data = b""
            while b"\r\n\r\n" not in data:
                data += sock.recv(4096)
            headers = dict(
                (k.strip().lower(), v.strip()) for k, _, v in (ln.partition(":") for ln in data.decode().split("\r\n")[1:])
            )
            accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + _GUID).encode()).digest()).decode()
            sock.sendall((
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode())
            self.conn = Conn(sock)
            self.script(self.conn)
        except (EOFError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001 - surfaced by the test
            self.error = exc

    def close(self):
        self.server.close()
