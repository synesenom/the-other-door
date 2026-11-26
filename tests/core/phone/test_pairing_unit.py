"""Pairing a phone with `door serve` (#302): one-time codes, device tokens stored only as hashes."""

import json
import stat
from datetime import UTC, datetime, timedelta

import pytest

from door.core.phone import pairing

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def test_a_code_is_redeemed_once_for_a_token_that_then_verifies(tmp_path):
    code = pairing.new_code(tmp_path, "Anna's Pixel", now=NOW)
    assert len(code.replace("-", "")) == 8

    got = pairing.redeem(tmp_path, code, now=NOW + timedelta(minutes=1))
    assert got is not None
    device, token = got
    assert device == "Anna's Pixel"
    assert len(token) >= 40
    assert pairing.verify(tmp_path, token) == "Anna's Pixel"
    assert pairing.redeem(tmp_path, code, now=NOW + timedelta(minutes=2)) is None  # once only
    assert pairing.verify(tmp_path, token + "x") is None
    assert pairing.verify(tmp_path, "") is None


def test_a_code_is_forgiving_about_case_and_the_dash(tmp_path):
    code = pairing.new_code(tmp_path, "phone", now=NOW)
    assert pairing.redeem(tmp_path, code.replace("-", "").lower(), now=NOW) is not None


def test_a_code_expires_after_ten_minutes(tmp_path):
    code = pairing.new_code(tmp_path, "phone", now=NOW)
    assert pairing.redeem(tmp_path, code, now=NOW + timedelta(minutes=10, seconds=1)) is None


def test_the_files_hold_hashes_only_and_are_private(tmp_path):
    code = pairing.new_code(tmp_path, "phone", now=NOW)
    _, token = pairing.redeem(tmp_path, code, now=NOW)
    folder = tmp_path / ".serve"
    for f in folder.iterdir():
        text = f.read_text()
        assert token not in text and code not in text and code.replace("-", "") not in text
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_devices_lists_and_unpair_revokes_one(tmp_path):
    _, token = pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel", now=NOW), now=NOW)
    assert [d["device"] for d in pairing.devices(tmp_path)] == ["Pixel"]
    assert "token" not in json.dumps(pairing.devices(tmp_path)).lower().replace("token_hash", "")
    assert pairing.unpair(tmp_path, "pixel") is True  # case-insensitive
    assert pairing.verify(tmp_path, token) is None
    assert pairing.unpair(tmp_path, "nobody") is False


def test_a_second_phone_is_refused_until_the_first_is_unpaired(tmp_path):
    pairing.redeem(tmp_path, pairing.new_code(tmp_path, "Pixel", now=NOW), now=NOW)
    for strong in (False, True):
        with pytest.raises(ValueError, match="unpair"):
            pairing.new_code(tmp_path, "iPad", now=NOW, strong=strong)
    pairing.unpair(tmp_path, "Pixel")
    assert pairing.new_code(tmp_path, "iPad", now=NOW)


def test_two_codes_made_before_either_is_used_pair_only_one_phone(tmp_path):
    first = pairing.new_code(tmp_path, "Pixel", now=NOW)
    second = pairing.new_code(tmp_path, "Tablet", now=NOW, strong=True)
    assert pairing.redeem(tmp_path, first, now=NOW)
    assert pairing.redeem(tmp_path, second, now=NOW) is None
    assert [d["device"] for d in pairing.devices(tmp_path)] == ["Pixel"]


def test_a_devices_file_of_several_phones_from_before_still_works(tmp_path):
    rows = [{"device": n, "token_hash": pairing._hash(t), "paired_at": "2026-01-01T00:00:00+00:00", "last_seen": None}
            for n, t in (("Pixel", "a"), ("iPad", "b"))]
    pairing._write(pairing._folder(tmp_path) / "devices.json", rows)
    assert pairing.verify(tmp_path, "a") == "Pixel" and pairing.verify(tmp_path, "b") == "iPad"
    with pytest.raises(ValueError, match="unpair"):
        pairing.new_code(tmp_path, "Third", now=NOW)
    pairing.unpair(tmp_path, "Pixel")
    pairing.unpair(tmp_path, "iPad")
    assert pairing.new_code(tmp_path, "Third", now=NOW)


def test_a_device_needs_a_name(tmp_path):
    with pytest.raises(ValueError):
        pairing.new_code(tmp_path, "  ", now=NOW)


def test_another_homes_token_does_not_verify(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _, token = pairing.redeem(a, pairing.new_code(a, "phone", now=NOW), now=NOW)
    assert pairing.verify(b, token) is None


def test_a_qr_code_is_long_and_short_lived(tmp_path):
    code = pairing.new_code(tmp_path, "Pixel", now=NOW, strong=True)
    assert len(code) == 24 and "-" not in code  # nobody types it: it can be long (about 2^119)
    assert pairing.redeem(tmp_path, code, now=NOW + timedelta(minutes=5, seconds=1)) is None
    code = pairing.new_code(tmp_path, "Pixel", now=NOW, strong=True)
    assert pairing.redeem(tmp_path, code, now=NOW + timedelta(minutes=4)) is not None


def test_a_new_qr_code_for_a_device_cancels_its_older_ones(tmp_path):
    first = pairing.new_code(tmp_path, "Pixel", now=NOW, strong=True)
    second = pairing.new_code(tmp_path, "Pixel", now=NOW, strong=True)
    assert pairing.redeem(tmp_path, first, now=NOW) is None
    assert pairing.redeem(tmp_path, second, now=NOW) is not None
