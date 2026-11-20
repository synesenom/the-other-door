"""`fonts.plan` (#199): which pinned family stands in for each font a CV names, on a small made-up pin so every rule
is pinned on its own; and `fonts.fetch`, with `pinned.http_get` replaced."""

from __future__ import annotations

import hashlib

import pytest

from door.core.downloads import pinned
from door.style import fonts


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


FILES = {}


def _family(name, klass, weights=(400, 700), italics=(False,), x=0.5, stem=0.09, adv=500, licence="OFL.txt"):
    files = []
    for italic in italics:
        for w in weights:
            fname = f"{name.replace(' ', '')}-{w}{'i' if italic else ''}.ttf"
            data = f"{name}:{fname}".encode()
            FILES[fname] = data
            files.append({"name": fname, "weight": w, "italic": italic, "sha256": _sha(data)})
    lic = f"licence of {name}".encode()
    FILES[f"{name}/{licence}"] = lic
    return {"commit": "a" * 40, "dir": f"ofl/{fonts.key(name)}", "class": klass,
            "licence": {"name": licence, "sha256": _sha(lic)}, "files": files,
            "metrics": {"x_height": x, "stem": stem, "advance": [adv] * len(fonts.ADVANCE_CHARS)}}


@pytest.fixture
def data():
    return {"version": 1, "url": "https://raw.githubusercontent.com/google/fonts/{commit}/{dir}/{name}",
            "families": {
                "Arimo": _family("Arimo", "sans", italics=(False, True)),
                "Tinos": _family("Tinos", "serif", licence="LICENSE.txt"),
                "Cousine": _family("Cousine", "fixed", adv=600),
                "Lato": _family("Lato", "sans", weights=(300, 400, 700, 900), italics=(False, True), adv=520, x=0.507),
                "Narrow": _family("Narrow", "sans", adv=400, x=0.45),
                "Crimson": _family("Crimson", "serif", adv=430),
                "Fraunces": _family("Fraunces", "serif", adv=470, x=0.46),
                "Carlito": _family("Carlito", "sans", adv=490),
            },
            "aliases": {"calibri": "Carlito", "arial": "Arimo", "helvetica": "Arimo", "timesnewroman": "Tinos"},
            "lookalikes": {"centurygothic": "Narrow"}}


def font(name, family, weight=400, italic=False, serif=False, fixed=False, icon=False, type3=False, chars=100):
    return {"font": name, "family": family, "weight": weight, "italic": italic, "serif": serif, "fixed": fixed,
            "embedded": True, "icon": icon, "type3": type3, "runs": 5, "chars": chars}


def one(fonts_, data, measured=None):
    return fonts.plan(fonts_, measured, data=data)


def test_a_family_in_the_pin_is_taken_by_name_whatever_its_spelling(data):
    for spelling in ("Lato", "LATO", "lato"):
        [p] = one([font("Lato-Regular", spelling)], data)
        assert (p["source"], p["resolved"], p["family"]) == ("name", "Lato", spelling)
    [p] = one([font("Lato-Regular", "Lato")], data)
    assert [f["name"] for f in p["files"]] == ["Lato-400.ttf"] and p["alternatives"] == []


def test_a_same_width_stand_in_is_taken_for_the_font_it_replaces(data):
    for family, wanted in (("Calibri", "Carlito"), ("Arial", "Arimo"), ("Helvetica", "Arimo"), ("TimesNewRomanPS", "Tinos"),
                           ("Times New Roman", "Tinos")):
        [p] = one([font(family + "-Regular", family, serif="Times" in family)], data)
        assert (p["source"], p["resolved"]) == ("standin", wanted), family
        assert wanted in p["reason"] and family in p["reason"] and "same widths" in p["reason"]


def test_a_look_alike_is_taken_but_not_said_to_have_the_same_widths(data):
    [p] = one([font("CenturyGothic", "Century Gothic")], data)
    assert (p["source"], p["resolved"]) == ("lookalike", "Narrow")
    assert "same widths" not in p["reason"] and "looks alike" in p["reason"] and "may differ" in p["reason"]


def test_a_look_alike_within_the_width_tolerance_comes_before_a_nearer_width(data):
    # width cannot tell shapes apart: a curated look-alike near enough in width wins over a family nearer still
    data["lookalikes"]["centurygothic"] = "Carlito"
    f = font("CenturyGothic", "Century Gothic")
    [p] = one([f], data, _measure("CenturyGothic", per_char=0.505))      # Arimo is nearer, Carlito within 6%
    assert (p["source"], p["resolved"]) == ("lookalike", "Carlito")
    assert "looks alike" in p["reason"] and "width within" in p["reason"]


def test_a_look_alike_too_far_in_width_comes_after_the_measured_nearest(data):
    f = font("CenturyGothic", "Century Gothic")
    [p] = one([f], data, _measure("CenturyGothic", per_char=0.49))       # Narrow is 18% off; Arimo and Carlito are within 6%
    assert p["source"] == "nearest" and p["resolved"] != "Narrow"
    [p] = one([f], data, _measure("CenturyGothic", per_char=0.8))         # nothing is: the look-alike, not the default
    assert (p["source"], p["resolved"]) == ("lookalike", "Narrow")


def test_a_look_alike_that_would_fake_more_of_the_cvs_faces_gives_way_to_the_nearest(data):
    # Narrow has no italic: a CV in italic keeps the family that has it
    data["lookalikes"]["centurygothic"] = "Carlito"
    f = font("CenturyGothic-Italic", "Century Gothic", italic=True)
    [p] = one([f], data, _measure("CenturyGothic-Italic", per_char=0.505))
    assert (p["source"], p["resolved"]) == ("nearest", "Arimo")


# ---------- whether a CV's look can be copied at all: its main fonts need one that looks alike ----------

def test_a_main_font_with_only_a_width_match_has_none_that_looks_alike(data):
    f = font("Palladio-Roma", "Palladio", serif=True, chars=900)
    plan = one([f], data, _measure("Palladio-Roma", per_char=0.43))
    assert fonts.unlike(plan, [f]) == ["Palladio"]


def test_fonts_by_name_stand_in_or_look_alike_look_alike_and_a_minor_font_does_not_count(data):
    main = [font("Lato-Regular", "Lato", chars=700), font("Calibri", "Calibri", chars=200), font("CenturyGothic", "Century Gothic", chars=200)]
    minor = font("Palladio-Italic", "Palladio", serif=True, italic=True, chars=30)  # under a tenth of the text
    plan = one([*main, minor], data, _measure("Palladio-Italic", per_char=0.43))
    assert fonts.unlike(plan, [*main, minor]) == []


def test_icon_fonts_are_not_counted_in_the_share(data):
    text = font("Palladio-Roma", "Palladio", serif=True, chars=100)
    icons = font("FontAwesome", "FontAwesome", icon=True, chars=5000)
    plan = one([text, icons], data, _measure("Palladio-Roma", per_char=0.43))
    assert fonts.unlike(plan, [text, icons]) == ["Palladio"]


def test_an_icon_font_is_not_fetched_and_a_font_with_no_family_is_left_out(data):
    plan = one([font("FontAwesome", "FontAwesome", icon=True), font("", "", type3=True), font("Lato-Regular", "Lato")], data)
    assert [p["family"] for p in plan] == ["Lato"]


def test_a_symbol_font_gets_nothing(data):
    [p] = one([font("CMSY10", "Computer Modern", serif=True)], data)
    assert (p["source"], p["resolved"], p["files"], p["licence"]) == ("none", None, [], None)
    assert "symbol" in p["reason"]


def test_the_files_are_the_nearest_weight_and_italic_the_cv_uses(data):
    fonts_ = [font("Lato-Regular", "Lato"), font("Lato-Bold", "Lato", weight=700), font("Lato-Semibold", "Lato", weight=600),
              font("Lato-Italic", "Lato", italic=True), font("Lato-Black", "Lato", weight=800)]
    [p] = one(fonts_, data)
    by_name = {f["name"]: f for f in p["files"]}
    assert set(by_name) == {"Lato-400.ttf", "Lato-700.ttf", "Lato-400i.ttf", "Lato-900.ttf"}
    assert by_name["Lato-700.ttf"]["for"] == [[600, False], [700, False]]
    assert by_name["Lato-900.ttf"]["for"] == [[800, False]]
    assert by_name["Lato-400i.ttf"]["italic"] is True


def test_an_italic_the_family_lacks_is_the_upright_face_and_is_said_faked(data):
    [p] = one([font("Tinos-Italic", "Tinos", italic=True, serif=True)], data)
    assert [f["name"] for f in p["files"]] == ["Tinos-400.ttf"]
    assert p["faked"] == [[400, True]] and "italic" in p["reason"] and "faked" in p["reason"]


def test_a_bold_the_family_lacks_is_faked_but_a_near_weight_is_not(data):
    data["families"]["Tinos"]["files"] = [f for f in data["families"]["Tinos"]["files"] if f["weight"] == 400]
    [p] = one([font("Tinos-Bold", "Tinos", weight=700, serif=True)], data)
    assert p["faked"] == [[700, False]]
    [q] = one([font("Lato-Semibold", "Lato", weight=600)], data)
    [r] = one([font("Lato-Regular", "Lato")], data)
    assert q["faked"] == r["faked"] == []


def test_among_tied_families_the_one_with_the_faces_the_cv_uses_comes_first(data):
    # Fraunces ties with Crimson on width but is the worse x-height; only Fraunces has an italic
    data["families"]["Fraunces"] = _family("Fraunces", "serif", italics=(False, True), adv=430, x=0.7)
    fonts_ = [font("Pal-Roma", "Pal", serif=True), font("Pal-Ital", "Pal", serif=True, italic=True)]
    [p] = one(fonts_, data, _measure("Pal-Roma", per_char=0.43, x=0.5))
    assert p["resolved"] == "Fraunces" and p["faked"] == []


def test_each_file_has_its_url_hash_and_the_family_its_licence_with_a_family_name(data):
    [p] = one([font("Tinos-Regular", "Tinos", serif=True)], data)
    f = p["files"][0]
    assert f["url"] == f"https://raw.githubusercontent.com/google/fonts/{'a' * 40}/ofl/tinos/Tinos-400.ttf"
    assert f["sha256"] == _sha(FILES["Tinos-400.ttf"])
    assert p["licence"]["name"] == "Tinos-LICENSE.txt"
    assert p["licence"]["url"].endswith("/ofl/tinos/LICENSE.txt") and p["licence"]["sha256"]


def _measure(font_name, size=10, x=0.5, stem=0.09, per_char=0.5, n=6):
    runs = [("abcdefghijklmnop", 16 * per_char * size, size)] * n
    return {font_name: {"x_height": x, "stem": stem, "runs": runs}}


def test_a_font_with_no_free_copy_gets_the_nearest_of_its_class_by_width(data):
    # the font's advance is 0.43 em a character: Crimson (430) is the serif, Narrow (400) is the nearest sans
    f = font("Palladio-Roma", "Palladio", serif=True)
    [p] = one([f], data, _measure("Palladio-Roma", per_char=0.43))
    assert (p["source"], p["resolved"]) == ("nearest", "Crimson")
    assert "Palladio" in p["reason"] and "Crimson" in p["reason"]
    assert [a["family"] for a in p["alternatives"]] == ["Fraunces", "Tinos"]
    g = font("Optima-Regular", "Optima")
    [q] = one([g], data, _measure("Optima-Regular", per_char=0.40))
    assert (q["source"], q["resolved"]) == ("nearest", "Narrow")


def test_the_class_filter_comes_before_the_width(data):
    [p] = one([font("Mono-Regular", "Mono", fixed=True)], data, _measure("Mono-Regular", per_char=0.4))
    assert p["resolved"] != "Narrow" and p["source"] == "none"   # Cousine alone is fixed and it is 50% wider


def test_a_tie_in_width_goes_to_the_closer_x_height_then_the_stem(data):
    data["families"]["Fraunces"]["metrics"]["advance"] = [430] * 63
    data["families"]["Fraunces"]["metrics"]["x_height"] = 0.44
    [p] = one([font("Pal-Roma", "Pal", serif=True)], data, _measure("Pal-Roma", per_char=0.43, x=0.44))
    assert p["resolved"] == "Fraunces"
    data["families"]["Fraunces"]["metrics"]["x_height"] = 0.7
    [p] = one([font("Pal-Roma", "Pal", serif=True)], data, _measure("Pal-Roma", per_char=0.43, x=0.5))
    assert p["resolved"] == "Crimson"


def test_too_far_a_match_is_the_class_default_with_none_and_a_reason(data):
    [p] = one([font("Wide-Regular", "Wide")], data, _measure("Wide-Regular", per_char=0.8))
    assert (p["source"], p["resolved"]) == ("none", "Arimo")
    assert "Wide" in p["reason"] and "%" in p["reason"] and p["files"]


def test_runs_with_no_width_are_no_measurement(data):
    runs = [("abcdefghijklmnop", 0, 10)] * 6
    [p] = one([font("Zero-Regular", "Zero")], data, {"Zero-Regular": {"x_height": 0.5, "stem": 0.09, "runs": runs}})
    assert p["source"] == "none" and p["resolved"] == "Arimo"


def test_with_no_measurement_the_class_default_stands_in(data):
    for fonts_, want in (([font("A-Regular", "A")], "Arimo"), ([font("B-Regular", "B", serif=True)], "Tinos"),
                         ([font("C-Regular", "C", fixed=True)], "Cousine")):
        [p] = one(fonts_, data)
        assert (p["source"], p["resolved"]) == ("none", want)
        assert "measure" in p["reason"]


def test_one_entry_per_family_in_order_of_use(data):
    plan = one([font("Lato-Regular", "Lato", chars=900), font("Tinos-Regular", "Tinos", serif=True, chars=20),
                font("Lato-Bold", "Lato", weight=700, chars=90)], data)
    assert [p["family"] for p in plan] == ["Lato", "Tinos"]


# ---------- fetch ----------

def _fetch(plan, dest, get):
    """`fonts.fetch` with the download replaced at its one place, `pinned.http_get`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pinned, "http_get", get)
        return fonts.fetch(plan, dest)


def _fake_fetch(calls=None, corrupt=None):
    def fetch(url, to):
        if calls is not None:
            calls.append(url)
        name = url.rsplit("/", 1)[1]
        folder = url.rsplit("/", 2)[1]
        key = name if name in FILES else next(k for k in FILES if k.endswith("/" + name) and k.lower().startswith(folder))
        to.write_bytes(b"corrupt" if name == corrupt else FILES[key])
    return fetch


def test_fetch_writes_each_file_and_the_licence_beside_it_checked_against_the_pin(data, tmp_path):
    plan = one([font("Lato-Regular", "Lato"), font("Lato-Bold", "Lato", weight=700)], data)
    paths = _fetch(plan, tmp_path / "fonts", _fake_fetch())
    assert sorted(p.name for p in paths) == ["Lato-400.ttf", "Lato-700.ttf"]
    assert (tmp_path / "fonts" / "Lato-400.ttf").read_bytes() == FILES["Lato-400.ttf"]
    assert (tmp_path / "fonts" / "Lato-OFL.txt").read_bytes() == FILES["Lato/OFL.txt"]
    assert sorted(p.name for p in (tmp_path / "fonts").iterdir()) == ["Lato-400.ttf", "Lato-700.ttf", "Lato-OFL.txt"]


def test_a_file_already_there_with_the_pinned_hash_is_not_fetched_again(data, tmp_path):
    plan = one([font("Lato-Regular", "Lato")], data)
    _fetch(plan, tmp_path, _fake_fetch())
    calls = []
    paths = _fetch(plan, tmp_path, _fake_fetch(calls))
    assert calls == [] and [p.name for p in paths] == ["Lato-400.ttf"]


def test_a_changed_file_is_fetched_again(data, tmp_path):
    plan = one([font("Lato-Regular", "Lato")], data)
    _fetch(plan, tmp_path, _fake_fetch())
    (tmp_path / "Lato-400.ttf").write_bytes(b"edited")
    _fetch(plan, tmp_path, _fake_fetch())
    assert (tmp_path / "Lato-400.ttf").read_bytes() == FILES["Lato-400.ttf"]


def test_a_download_that_does_not_match_the_pin_writes_nothing(data, tmp_path):
    plan = one([font("Lato-Regular", "Lato"), font("Lato-Bold", "Lato", weight=700)], data)
    with pytest.raises(fonts.FontsError, match="checksum"):
        _fetch(plan, tmp_path / "fonts", _fake_fetch(corrupt="Lato-700.ttf"))
    assert list((tmp_path / "fonts").iterdir()) == []   # not the good file, not a staging folder


def test_a_failing_download_is_a_fonts_error_and_leaves_no_partial_file(data, tmp_path):
    def broken(url, to):
        to.write_bytes(b"half")
        raise OSError("connection reset")
    plan = one([font("Lato-Regular", "Lato")], data)
    with pytest.raises(fonts.FontsError, match="connection reset"):
        _fetch(plan, tmp_path, broken)
    assert list(tmp_path.iterdir()) == []


def test_a_plan_with_nothing_to_fetch_makes_no_request(data, tmp_path):
    plan = one([font("CMSY10", "Computer Modern", serif=True)], data)
    calls = []
    assert _fetch(plan, tmp_path / "x", _fake_fetch(calls)) == [] and calls == []


def test_a_staging_folder_a_killed_fetch_left_is_swept_and_a_fresh_one_kept(data, tmp_path):
    import os
    old, fresh = tmp_path / ".fonts.old.part", tmp_path / ".fonts.new.part"
    old.mkdir(), fresh.mkdir()
    os.utime(old, (0, 0))
    _fetch(one([font("Lato-Regular", "Lato")], data), tmp_path, _fake_fetch())
    assert not old.exists() and fresh.exists()


REAL_LOOKALIKES = {"Aptos": "Arimo", "Segoe UI": "Open Sans", "Helvetica Neue": "Arimo", "HelveticaNeue": "Arimo",
                   "Verdana": "Work Sans", "Garamond": "EB Garamond", "Palatino": "Spectral",
                   "Palatino Linotype": "Spectral", "Book Antiqua": "Spectral", "Optima": "Asap",
                   "Avenir": "Lato", "Avenir Next": "Lato",
                   "AdobeGaramondPro": "EB Garamond", "AGaramondPro-Regular": "EB Garamond",
                   "AvenirNextLTPro-Regular": "Lato", "Avenir Next LT Pro": "Lato",
                   "HelveticaNeueLTStd-Roman": "Arimo", "AptosDisplay": "Arimo", "Aptos Display": "Arimo"}


@pytest.mark.parametrize("name,family", sorted(REAL_LOOKALIKES.items()))
def test_the_real_pin_gives_each_unmeasured_commercial_font_a_look_alike(name, family):
    serif = family in ("EB Garamond", "Spectral")
    [p] = fonts.plan([font(name.replace(" ", "") + "-Regular", name, serif=serif)])
    assert (p["source"], p["resolved"]) == ("lookalike", family)
    assert "same widths" not in p["reason"] and "may differ" in p["reason"]


def test_on_the_real_pin_tahoma_looks_like_fira_sans_when_near_in_width():
    # runs as wide as Fira Sans would set them: several families are as near, the look-alike is taken
    table = dict(zip(fonts.ADVANCE_CHARS, fonts.pin()["families"]["Fira Sans"]["metrics"]["advance"]))
    text = "abcdefghijklmnop"
    width = (sum(table[c] for c in text) / 1000 - fonts.BEARING) * 10
    measured = {"Tahoma": {"x_height": 0.545, "stem": 0.09, "runs": [(text, width, 10)] * 6}}
    [p] = fonts.plan([font("Tahoma", "Tahoma")], measured)
    assert (p["source"], p["resolved"]) == ("lookalike", "Fira Sans")


def test_on_the_real_pin_a_measured_font_far_from_every_family_gets_the_look_alike_not_the_default():
    [p] = fonts.plan([font("Verdana-Regular", "Verdana")], _measure("Verdana-Regular", per_char=1.5))
    assert (p["source"], p["resolved"]) == ("lookalike", "Work Sans")


def test_a_pin_with_only_some_families_never_names_one_it_lacks():
    # the offline fallback of style_build: only the families the code ships
    data = fonts.pin()
    data["families"] = {n: f for n, f in data["families"].items() if n in ("Figtree", "Young Serif")}
    plan = fonts.plan([font("Aptos-Regular", "Aptos"), font("Calibri-Regular", "Calibri"),
                       font("CenturyGothic", "Century Gothic")], data=data)
    assert [(p["family"], p["resolved"]) for p in plan] == [("Aptos", None), ("Calibri", None), ("Century Gothic", None)]


@pytest.mark.parametrize("name", ["Alato", "Aarimo"])
def test_a_name_that_only_starts_with_a_lowercase_a_is_not_read_as_adobes_prefix(name):
    [p] = fonts.plan([font(name + "-Regular", name)])
    assert p["source"] == "none"


# ---------- a family pinned from its own source, and one converted to TrueType ----------

def _cff_font() -> bytes:
    """A one-glyph OpenType font with CFF outlines, the kind Chromium prints as nameless text."""
    import io

    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder([".notdef", "l"])
    fb.setupCharacterMap({ord("l"): "l"})
    pen = T2CharStringPen(500, None)
    pen.moveTo((100, 0)), pen.lineTo((100, 700)), pen.curveTo((150, 750), (200, 750), (250, 700)), pen.lineTo((250, 0))
    pen.closePath()
    fb.setupCFF("Test-Regular", {"FullName": "Test Regular"}, {".notdef": T2CharStringPen(500, None).getCharString(),
                                                                "l": pen.getCharString()}, {})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "l": (350, 100)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    fb.setupOS2(), fb.setupPost()
    out = io.BytesIO()
    fb.save(out)
    return out.getvalue()


def _own_source(data, convert=False):
    body = _cff_font() if convert else b"plain ttf"
    source = "Own-Regular.otf" if convert else "Own-Regular.ttf"
    FILES[source] = body
    FILES["Own/LICENCE.TXT"] = b"own licence"
    data["families"]["Own"] = {
        "url": "https://example.org/fonts/{name}", "class": "serif",
        "licence": {"name": "LICENCE.TXT", "sha256": _sha(b"own licence"), "url": "https://example.org/doc/LICENCE.TXT"},
        "files": [{"name": "Own-Regular.ttf", "weight": 400, "italic": False, "sha256": _sha(body),
                   **({"from": source} if convert else {})}],
        "metrics": data["families"]["Tinos"]["metrics"]}
    data["aliases"]["ownface"] = "Own"


def _own_fetch(calls):
    def fetch(url, to):
        calls.append(url)
        to.write_bytes(FILES["Own/LICENCE.TXT"] if url.endswith("LICENCE.TXT") else FILES[url.rsplit("/", 1)[1]])
    return fetch


def test_a_family_pinned_from_its_own_source_is_fetched_from_there_with_its_licence(data, tmp_path):
    _own_source(data)
    [p] = one([font("OwnFace-Regular", "OwnFace", serif=True)], data)
    calls = []
    _fetch([p], tmp_path, _own_fetch(calls))
    assert sorted(calls) == ["https://example.org/doc/LICENCE.TXT", "https://example.org/fonts/Own-Regular.ttf"]
    assert (tmp_path / "Own-Regular.ttf").read_bytes() == b"plain ttf" and (tmp_path / "Own-LICENCE.TXT").is_file()


def test_an_opentype_cff_font_is_checked_as_pinned_then_written_as_truetype(data, tmp_path):
    from fontTools.ttLib import TTFont

    _own_source(data, convert=True)
    [p] = one([font("OwnFace-Regular", "OwnFace", serif=True)], data)
    calls = []
    [path] = _fetch([p], tmp_path, _own_fetch(calls))
    assert path.name == "Own-Regular.ttf" and "https://example.org/fonts/Own-Regular.otf" in calls
    converted = TTFont(path)
    assert "glyf" in converted and "CFF " not in converted and converted["hmtx"]["l"][0] == 350
    calls.clear()
    _fetch([p], tmp_path, _own_fetch(calls))
    assert calls == []   # already there: not fetched or converted again
