"""The pinned free fonts (#199): `style/fonts_pin.json`, written by scripts/pin_fonts.py. Each family is pinned at the last
google/fonts commit where it was still static, with the sha256 of every file and of its licence."""

from __future__ import annotations

import re

from door.style import fonts

_URL = re.compile(r"^https://raw\.githubusercontent\.com/google/fonts/[0-9a-f]{40}/(ofl|apache)/[a-z0-9]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def test_the_pin_has_families_in_three_classes():
    assert {f["class"] for f in fonts.pin()["families"].values()} == {"sans", "serif", "fixed"}


def test_every_file_and_licence_url_is_a_raw_google_fonts_commit_path():
    data = fonts.pin()
    for name, fam in data["families"].items():
        for file in fam["files"]:
            assert _URL.match(fonts.file_url(name, file["name"], data)), (name, file["name"])
        assert _URL.match(data["url"].format(commit=fam["commit"], dir=fam["dir"], name=fam["licence"]["name"])), name


def test_each_family_has_a_regular_static_file_and_a_licence():
    for name, fam in fonts.pin()["families"].items():
        assert any(f["weight"] == 400 and not f["italic"] for f in fam["files"]), name
        assert not any("[" in f["name"] or "]" in f["name"] for f in fam["files"]), name   # static only
        assert all(f["name"].endswith(".ttf") for f in fam["files"]), name
        assert _SHA.match(fam["licence"]["sha256"]) and fam["licence"]["name"] in ("OFL.txt", "LICENSE.txt"), name
        assert all(_SHA.match(f["sha256"]) for f in fam["files"]), name
        assert re.fullmatch(r"[0-9a-f]{40}", fam["commit"]), name


def test_no_family_has_two_files_of_the_same_weight_and_style():
    for name, fam in fonts.pin()["families"].items():
        faces = [(f["weight"], f["italic"]) for f in fam["files"]]
        assert len(faces) == len(set(faces)), name


def test_each_family_carries_its_metrics():
    for name, fam in fonts.pin()["families"].items():
        m = fam["metrics"]
        assert 0.3 < m["x_height"] < 0.8 and 0 < m["stem"] < 0.5 and "cap_height" not in m, name
        assert len(m["advance"]) == len(fonts.ADVANCE_CHARS) == 63 and all(0 < v < 1500 for v in m["advance"]), name


def test_every_alias_names_a_pinned_family_and_is_written_in_the_normalised_form():
    data = fonts.pin()
    for table in ("aliases", "lookalikes"):
        assert all(target in data["families"] for target in data[table].values()), table
        assert all(key == fonts.key(key) for key in data[table]), table
    assert not set(data["aliases"]) & set(data["lookalikes"])
