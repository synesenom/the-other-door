"""scripts/pin_fonts.py (#199): the parts that need no network, on a font the repo ships."""

import importlib.util

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


def _run_with_existing(tmp_path, monkeypatch, argv):
    import json
    out = tmp_path / "pin.json"
    existing = fonts.pin()
    pin_fonts.write(existing, out)
    before = out.read_bytes()
    seen = []

    def fake(name, klass, folders, cache):
        seen.append(name)
        return {**existing["families"][name], "commit": "f" * 40}, None

    monkeypatch.setattr(pin_fonts, "pin_family", fake)
    assert pin_fonts.main([*argv, "--out", str(out)]) == 0
    return existing, before, out, seen, json.loads(out.read_text())


def test_only_re_pins_the_named_family_and_leaves_every_other_one_byte_for_byte(tmp_path, monkeypatch):
    existing, before, out, seen, now = _run_with_existing(tmp_path, monkeypatch, ["--only", "Lato"])
    assert seen == ["Lato"]
    assert now["families"]["Lato"]["commit"] == "f" * 40
    assert {k: v for k, v in now["families"].items() if k != "Lato"} == \
        {k: v for k, v in existing["families"].items() if k != "Lato"}
    assert now["aliases"] == existing["aliases"] and now["lookalikes"] == existing["lookalikes"]


def test_tables_only_pins_nothing_and_changes_nothing_when_the_tables_are_current(tmp_path, monkeypatch):
    _, before, out, seen, _ = _run_with_existing(tmp_path, monkeypatch, ["--tables-only"])
    assert seen == [] and out.read_bytes() == before


def test_tables_only_rewrites_just_the_tables(tmp_path, monkeypatch):
    import json
    out = tmp_path / "pin.json"
    stale = {**fonts.pin(), "aliases": {}, "lookalikes": {}}
    pin_fonts.write(stale, out)
    monkeypatch.setattr(pin_fonts, "pin_family", lambda *a: (_ for _ in ()).throw(AssertionError("pinned")))
    pin_fonts.main(["--tables-only", "--out", str(out)])
    now = json.loads(out.read_text())
    assert now["families"] == stale["families"]
    assert now["aliases"] == fonts.pin()["aliases"] and now["lookalikes"] == fonts.pin()["lookalikes"]
