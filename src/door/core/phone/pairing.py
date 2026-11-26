"""Pairing phones with `door serve` (#302): one-time codes and device tokens, kept per data folder.

`serve pair` makes a code (8 characters, shown as XXXX-XXXX, valid ten minutes, good once); the phone
trades it for a device token (`redeem`) and sends that token with every request (`verify`). Both live in
`<home>/.serve/` (a 0700 folder, 0600 files) only as SHA-256 hashes: a stolen file pairs nothing.
Each home pairs one phone. Each home is its own instance, so another person's token never verifies here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from door.core import utils

CODE_TTL = timedelta(minutes=10)
STRONG_TTL = timedelta(minutes=5)   # a QR code: nobody types it, so it is long and lives briefly
STRONG_LENGTH = 24
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: read off a screen and typed


def _folder(home: Path) -> Path:
    folder = Path(home) / ".serve"
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    return folder


def _read(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write(path: Path, rows: list[dict]) -> None:
    utils.write_atomic(path, json.dumps(rows, indent=2), mode=0o600)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _norm_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def devices(home: Path) -> list[dict]:
    """The paired devices, oldest first: name, when paired, when last seen (never the token)."""
    return [{k: d.get(k) for k in ("device", "paired_at", "last_seen")} for d in _read(_folder(home) / "devices.json")]


def new_code(home: Path, device: str, *, now: datetime | None = None, strong: bool = False) -> str:
    """A one-time pairing code for a device of this name; its hash is kept, not the code.

    `XXXX-XXXX` (ten minutes) to type from a terminal; `strong` is the QR code's: 24 characters
    (about 2^119), five minutes, and it cancels the device's older codes. One phone at a time: while
    one is paired, no code is made until it is unpaired.
    """
    device = device.strip()
    if not device:
        raise ValueError("name the device, e.g. --device \"Anna's phone\"")
    paired = devices(home)
    if paired:
        raise ValueError(f"Only one phone can be paired: unpair {paired[0]['device']!r} first to pair another.")
    folder = _folder(home)
    at = _now(now)
    code = "".join(secrets.choice(_ALPHABET) for _ in range(STRONG_LENGTH if strong else 8))
    pending = [p for p in _read(folder / "pairing.json") if datetime.fromisoformat(p["expires"]) > at]
    if strong:
        pending = [p for p in pending if p["device"].casefold() != device.casefold()]
    pending.append({"device": device, "code_hash": _hash(code), "expires": (at + (STRONG_TTL if strong else CODE_TTL)).isoformat()})
    _write(folder / "pairing.json", pending)
    return code if strong else f"{code[:4]}-{code[4:]}"


def redeem(home: Path, code: str, *, now: datetime | None = None) -> tuple[str, str] | None:
    """Trade a code for a new device token: `(device, token)`, or None for a wrong, used or old code."""
    folder = _folder(home)
    at = _now(now)
    wanted = _hash(_norm_code(code))
    pending = _read(folder / "pairing.json")
    match = next((p for p in pending if hmac.compare_digest(p["code_hash"], wanted)), None)
    rest = [p for p in pending if p is not match and datetime.fromisoformat(p["expires"]) > at]
    _write(folder / "pairing.json", rest)
    if match is None or datetime.fromisoformat(match["expires"]) < at:
        return None
    rows = [d for d in _read(folder / "devices.json") if d["device"].casefold() != match["device"].casefold()]
    if rows:  # one phone: a code made before another phone paired no longer pairs
        return None
    token = secrets.token_urlsafe(32)
    rows.append({"device": match["device"], "token_hash": _hash(token), "paired_at": at.isoformat(), "last_seen": None})
    _write(folder / "devices.json", rows)
    return match["device"], token


def verify(home: Path, token: str) -> str | None:
    """The device a token belongs to, or None. Every stored hash is compared, in constant time each."""
    if not token:
        return None
    wanted = _hash(token)
    found = None
    for d in _read(_folder(home) / "devices.json"):
        if hmac.compare_digest(d.get("token_hash", ""), wanted):
            found = d["device"]
    return found


def touch(home: Path, device: str, *, now: datetime | None = None) -> None:
    """Note when a device was last seen (for `serve devices`)."""
    path = _folder(home) / "devices.json"
    rows = _read(path)
    for d in rows:
        if d["device"] == device:
            d["last_seen"] = _now(now).isoformat()
    _write(path, rows)


def unpair(home: Path, device: str) -> bool:
    """Revoke a device by name (any case); False when there is none."""
    path = _folder(home) / "devices.json"
    rows = _read(path)
    keep = [d for d in rows if d["device"].casefold() != device.strip().casefold()]
    if len(keep) == len(rows):
        return False
    _write(path, keep)
    return True
