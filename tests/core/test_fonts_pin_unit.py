"""The pinned free fonts (#199): `core/fonts_pin.json`, written by scripts/pin_fonts.py. Each family is pinned at the last
google/fonts commit where it was still static, with the sha256 of every file and of its licence."""

from __future__ import annotations

import re

from door.core import fonts

_URL = re.compile(r"^https://raw\.githubusercontent\.com/google/fonts/[0-9a-f]{40}/(ofl|apache)/[a-z0-9]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CROSCORE = {"Arimo", "Tinos", "Cousine", "Carlito", "Caladea"}


def _families():
    return fonts.pin()["families"]


def test_there_are_about_fifty_families_in_three_classes():
    families = _families()
    assert 35 <= len(families) <= 80
    assert {f["class"] for f in families.values()} == {"sans", "serif", "fixed"}


def test_every_file_and_licence_url_is_a_raw_google_fonts_commit_path():
    for name in _families():
        for file in fonts.pin()["families"][name]["files"]:
            assert _URL.match(fonts.file_url(name, file["name"])), (name, file["name"])
        assert _URL.match(fonts.licence_url(name)), name


def test_each_family_has_a_regular_static_file_and_a_licence():
    for name, fam in _families().items():
        assert any(f["weight"] == 400 and not f["italic"] for f in fam["files"]), name
        assert not any("[" in f["name"] or "]" in f["name"] for f in fam["files"]), name   # static only
        assert all(f["name"].endswith(".ttf") for f in fam["files"]), name
        assert _SHA.match(fam["licence"]["sha256"]) and fam["licence"]["name"] in ("OFL.txt", "LICENSE.txt"), name
        for f in fam["files"]:
            assert _SHA.match(f["sha256"]) and f["size"] > 1000, (name, f["name"])
        assert re.fullmatch(r"[0-9a-f]{40}", fam["commit"]), name


def test_each_family_carries_its_metrics():
    for name, fam in _families().items():
        m = fam["metrics"]
        assert 0.3 < m["x_height"] < 0.8 and 0.5 < m["cap_height"] < 0.95 and 0 < m["stem"] < 0.5, name
        assert len(m["advance"]) == len(fonts.ADVANCE_CHARS) == 63 and all(0 < v < 1500 for v in m["advance"]), name


def test_the_free_stand_ins_for_the_common_fonts_are_pinned():
    assert _CROSCORE <= set(_families())
    assert "Lato" in _families() and "Young Serif" in _families()


def test_every_alias_names_a_pinned_family():
    aliases = fonts.pin()["aliases"]
    assert aliases["calibri"] == "Carlito" and aliases["cambria"] == "Caladea"
    assert aliases["arial"] == aliases["helvetica"] == aliases["texgyreheros"] == aliases["nimbussansl"] == "Arimo"
    assert aliases["timesnewroman"] == "Tinos" and aliases["couriernew"] == "Cousine"
    assert all(target in _families() for target in aliases.values())
    assert all(key == fonts.key(key) for key in aliases)   # aliases are written in the normalised form
