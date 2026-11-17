"""scripts/pin_fonts.py (#199): the parts that need no network, on a font the repo ships."""

import importlib.util
import json

import pytest

from paths import REPO_ROOT

from door.core import fonts, workspace

_spec = importlib.util.spec_from_file_location("pin_fonts", REPO_ROOT / "scripts" / "pin_fonts.py")
pin_fonts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pin_fonts)


def test_a_font_is_measured_in_em_fractions_with_an_advance_per_character():
    m = pin_fonts.measure_font(workspace.PROFILE_EXAMPLE_DIR / "fonts" / "Figtree-Regular.ttf")
    assert 0.45 < m["x_height"] < 0.55 and "cap_height" not in m and 0.03 < m["stem"] < 0.15
    assert len(m["advance"]) == len(fonts.ADVANCE_CHARS)
    assert m["advance"][fonts.ADVANCE_CHARS.index(" ")] < m["advance"][fonts.ADVANCE_CHARS.index("m")]


def test_weights_and_italics_are_read_off_the_file_names():
    assert pin_fonts.weight_italic("Lato-BoldItalic.ttf") == (700, True)
    assert pin_fonts.weight_italic("PT_Sans-Web-Regular.ttf") == (400, False)
    assert pin_fonts.weight_italic("Lato-Black.ttf") == (900, False)


def test_a_short_style_suffix_is_read_too():
    assert [pin_fonts.weight_italic(f"GenBkBas{s}.ttf") for s in ("R", "I", "B", "BI")] == [
        (400, False), (400, True), (700, False), (700, True)]


def test_every_alias_the_script_writes_is_in_normal_form_and_a_listed_family():
    listed = {name for name, _, _ in pin_fonts.FAMILIES}
    for table in (pin_fonts.ALIASES, pin_fonts.LOOKALIKES):
        for target, names in table.items():
            assert target in listed
            assert all(n == fonts.key(n) for n in names)


def test_the_pins_alias_and_look_alike_tables_are_what_the_script_writes():
    pin = fonts.pin()
    for name, table in (("aliases", pin_fonts.ALIASES), ("lookalikes", pin_fonts.LOOKALIKES)):
        want = {a: target for target, keys in table.items() if target in pin["families"] for a in keys}
        assert pin[name] == dict(sorted(want.items())), name


def _run_with_existing(tmp_path, monkeypatch, argv, pin=None, fails=()):
    out = tmp_path / "pin.json"
    existing = pin or fonts.pin()
    pin_fonts.write(existing, out)
    before = out.read_bytes()
    seen = []

    def fake(name, klass, folders, cache):
        seen.append(name)
        if name in fails:
            return None, "variable only"
        return {**fonts.pin()["families"][name], "commit": "f" * 40}, None

    monkeypatch.setattr(pin_fonts, "pin_family", fake)
    assert pin_fonts.main([*argv, "--out", str(out)]) == 0
    return existing, before, out, seen, json.loads(out.read_text())


def _written(pin, path):
    pin_fonts.write(pin, path)
    return path.read_text()


def test_every_pinned_family_is_in_families():
    assert set(fonts.pin()["families"]) <= {name for name, _, _ in pin_fonts.FAMILIES}


def test_only_re_pins_the_named_family_and_leaves_every_other_one_byte_for_byte(tmp_path, monkeypatch):
    existing, before, out, seen, now = _run_with_existing(tmp_path, monkeypatch, ["--only", "Lato"])
    assert seen == ["Lato"]
    assert now["families"]["Lato"]["commit"] == "f" * 40
    # the file as written, with Lato's entry taken from the new pin: identical text outside Lato's entry
    expected = {**existing, "families": {**existing["families"], "Lato": now["families"]["Lato"]}}
    assert out.read_text() == _written(expected, tmp_path / "expected.json")
    assert now["aliases"] == existing["aliases"] and now["lookalikes"] == existing["lookalikes"]


def test_only_adds_a_family_not_pinned_yet_in_sorted_place_and_its_table_entries(tmp_path, monkeypatch):
    full = fonts.pin()
    bare = {**full, "families": {k: v for k, v in full["families"].items() if k != "Lato"},
            "lookalikes": {k: v for k, v in full["lookalikes"].items() if v != "Lato"}}
    _, _, _, seen, now = _run_with_existing(tmp_path, monkeypatch, ["--only", "Lato"], pin=bare)
    assert seen == ["Lato"]
    assert list(now["families"]) == sorted(full["families"])
    assert now["lookalikes"] == full["lookalikes"]


def test_only_keeps_the_old_entry_of_a_family_that_fails_to_pin(tmp_path, monkeypatch):
    existing, before, out, seen, now = _run_with_existing(tmp_path, monkeypatch, ["--only", "Lato"], fails={"Lato"})
    assert seen == ["Lato"] and out.read_bytes() == before


def test_only_refuses_a_name_that_is_not_in_families(tmp_path, monkeypatch):
    monkeypatch.setattr(pin_fonts, "pin_family", lambda *a: (_ for _ in ()).throw(AssertionError("pinned")))
    out = tmp_path / "pin.json"
    pin_fonts.write(fonts.pin(), out)
    with pytest.raises(SystemExit) as exc:
        pin_fonts.main(["--only", "Latoo", "--out", str(out)])
    assert exc.value.code != 0


def test_a_bare_only_does_not_re_pin_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(pin_fonts, "pin_family", lambda *a: (_ for _ in ()).throw(AssertionError("pinned")))
    out = tmp_path / "pin.json"
    pin_fonts.write(fonts.pin(), out)
    with pytest.raises(SystemExit) as exc:
        pin_fonts.main(["--only", "--out", str(out)])
    assert exc.value.code != 0


def test_only_and_tables_only_exclude_each_other(tmp_path):
    with pytest.raises(SystemExit) as exc:
        pin_fonts.main(["--only", "Lato", "--tables-only", "--out", str(tmp_path / "pin.json")])
    assert exc.value.code != 0


def test_tables_only_pins_nothing_and_changes_nothing_when_the_tables_are_current(tmp_path, monkeypatch):
    _, before, out, seen, _ = _run_with_existing(tmp_path, monkeypatch, ["--tables-only"])
    assert seen == [] and out.read_bytes() == before


def test_tables_only_rewrites_just_the_tables(tmp_path, monkeypatch):
    out = tmp_path / "pin.json"
    stale = {**fonts.pin(), "aliases": {}, "lookalikes": {}}
    pin_fonts.write(stale, out)
    monkeypatch.setattr(pin_fonts, "pin_family", lambda *a: (_ for _ in ()).throw(AssertionError("pinned")))
    pin_fonts.main(["--tables-only", "--out", str(out)])
    now = json.loads(out.read_text())
    assert now["families"] == stale["families"]
    assert now["aliases"] == fonts.pin()["aliases"] and now["lookalikes"] == fonts.pin()["lookalikes"]
