"""The stdlib DevTools websocket client (#165) against an in-process fake server."""

from __future__ import annotations

import time

import pytest

from door.render.cdp import Cdp, CdpError, CdpTimeout
from ws_fake import FakeWs


@pytest.fixture
def ws():
    made = []

    def make(script):
        fake = FakeWs(script)
        made.append(fake)
        return fake

    yield make
    for fake in made:
        fake.close()


def test_handshake_send_and_reply_matched_by_id(ws):
    seen = []

    def script(conn):
        msg = conn.read_json()
        seen.append((msg, conn.masked_ok))
        conn.send_json({"id": msg["id"], "result": {"ok": 1}})

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    assert cdp.send("Page.enable", {"a": 1}) == {"ok": 1}
    cdp.close()
    assert seen[0][0]["method"] == "Page.enable" and seen[0][0]["params"] == {"a": 1}
    assert seen[0][1] is True  # client frames are masked


def test_a_session_id_is_sent_with_the_command(ws):
    got = []

    def script(conn):
        msg = conn.read_json()
        got.append(msg)
        conn.send_json({"id": msg["id"], "result": {}})

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    cdp.send("Page.enable", session_id="S1")
    assert got[0]["sessionId"] == "S1"


def test_events_before_the_reply_are_queued_and_waited_for(ws):
    def script(conn):
        msg = conn.read_json()
        conn.send_json({"method": "Page.loadEventFired", "params": {"t": 5}})
        conn.send_json({"id": msg["id"], "result": {}})

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    cdp.send("Page.navigate")
    assert cdp.wait_event("Page.loadEventFired", timeout=2) == {"t": 5}


def test_a_handler_may_post_and_its_reply_is_dropped(ws):
    def script(conn):
        first = conn.read_json()
        for i in range(3000):  # a flood of events, each answered from the handler: no recursion
            conn.send_json({"method": "Fetch.requestPaused", "params": {"requestId": f"r{i}"}, "sessionId": "S"})
        for _ in range(3000):
            inner = conn.read_json()
            assert inner["method"] == "Fetch.failRequest"
            conn.send_json({"id": inner["id"], "result": {}})
        conn.send_json({"id": first["id"], "result": {"done": True}})

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    cdp.on("Fetch.requestPaused", lambda p, sid: cdp.post("Fetch.failRequest", {"requestId": p["requestId"]}, session_id=sid))
    assert cdp.send("Page.navigate", timeout=10) == {"done": True}
    assert fake.error is None
    assert not cdp._replies


@pytest.mark.parametrize("size,form", [(200, "16"), (70_000, "64")])
def test_long_frames_in_the_16_and_64_bit_forms(ws, size, form):
    blob = "x" * size

    def script(conn):
        msg = conn.read_json()
        conn.send_json({"id": msg["id"], "result": {"blob": blob}}, length_form=form)

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    assert cdp.send("Big", {"in": "y" * size})["blob"] == blob  # a long masked client frame too


def test_fragments_and_pings(ws):
    import json

    def script(conn):
        msg = conn.read_json()
        text = json.dumps({"id": msg["id"], "result": {"v": "joined"}}).encode()
        conn.write(b"hi", opcode=0x9)  # ping first
        conn.write(text[:10], opcode=0x1, fin=False)
        conn.write(text[10:20], opcode=0x0, fin=False)
        conn.write(text[20:], opcode=0x0, fin=True)

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    assert cdp.send("Frag") == {"v": "joined"}


def test_a_cdp_error_raises(ws):
    def script(conn):
        msg = conn.read_json()
        conn.send_json({"id": msg["id"], "error": {"code": -32000, "message": "no such thing"}})

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    with pytest.raises(CdpError, match="no such thing"):
        cdp.send("Bad")


def test_no_reply_by_the_deadline_is_a_timeout(ws):
    def script(conn):
        conn.read_json()
        time.sleep(2)

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    t0 = time.monotonic()
    with pytest.raises(CdpTimeout):
        cdp.send("Slow", timeout=0.3)
    assert time.monotonic() - t0 < 1.5
    with pytest.raises(CdpTimeout):
        cdp.wait_event("Never", timeout=0.2)


def test_a_closed_connection_raises(ws):
    def script(conn):
        conn.read_json()
        conn.sock.close()

    fake = ws(script)
    cdp = Cdp.connect(fake.url)
    with pytest.raises(CdpError):
        cdp.send("Gone")
