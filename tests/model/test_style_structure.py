"""The CV structure read by the real Haiku on the local claude's plan (#343, epic #342).

Not in the offline suite or CI (marker `model`): `./scripts/run-test.sh --model`, before a release. Each case is
`style_structure.extract` on a CV of the style corpus (the real scrubbed ones and the made-up designs, among them
the hand-written CVs a rule gets wrong: entry titles in the headings' style, headings in capitals in the body font, a
three-column CV, a designed CV with a "Page N of M" footer), made as the style build makes it: the real model, the
checks of `style_structure.check`. What is checked is behaviour: the verdict, the column count and the side band
(within 6 pt of the recorded one), the headings found (their texts as a multiset), that a second read of the same file
asks nothing (the cache) and that a rerun of the model gives the same headings (stability)."""

import json

import pytest

from conftest import claude_ready
from paths import TESTS_DIR

from door.style import style_extract, style_structure

pytestmark = pytest.mark.model

STYLES = TESTS_DIR / "style" / "fixtures" / "styles"
EXPECTED = json.loads((STYLES / "expected.json").read_text(encoding="utf-8"))
CASES = sorted(stem for stem in EXPECTED if stem != "scan")
RERUNS = ("latex-sidebar", "de-titles-same-style", "de-caps-headings-in-body-font", "html-equal-columns")


@pytest.fixture(scope="module")
def read(tmp_path_factory):
    """Each case read once, when a test first asks: name -> its style, read through the real model."""
    if reason := claude_ready():
        pytest.skip(reason)
    home = tmp_path_factory.mktemp("structure")
    done: dict[str, dict] = {}
    calls: list[str] = []
    real = style_structure._ask

    def counted(text, feature="style"):
        calls.append(text)
        return real(text, feature)

    def go(name: str) -> dict:
        if name not in done:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(style_structure, "_cache_dir", lambda: home / "cache")
                mp.setattr(style_structure, "_ask", counted)
                done[name] = style_structure.extract(STYLES / f"{name}.pdf")
        return done[name]

    go.calls, go.home = calls, home
    return go


@pytest.mark.parametrize("name", CASES)
def test_the_verdict_and_the_columns_are_the_corpus(read, name):
    style, expected = read(name), EXPECTED[name]
    assert {k: style["verdict"][k] for k in ("copyable", "reason")} == expected["verdict"]
    if not expected["verdict"]["copyable"]:
        return
    assert style["columns"]["count"] == expected["columns"]
    side = [b for b in style["columns"]["bands"] if b["kind"] == "side"]
    assert bool(side) == ("side_x" in expected)
    if side:
        assert all(abs(a - b) <= 6 for a, b in zip([side[0]["x0"], side[0]["x1"]], expected["side_x"]))


@pytest.mark.parametrize("name", [n for n in CASES if "headings" in EXPECTED[n]])
def test_the_headings_are_those_of_the_corpus(read, name):
    assert sorted(h["text"] for h in read(name)["headings"]) == EXPECTED[name]["headings"]


@pytest.mark.parametrize("name", [n for n in CASES if EXPECTED[n]["verdict"]["copyable"]])
def test_the_name_is_the_largest_text_of_the_first_page(read, name):
    style = read(name)
    assert style["name"] and style["name"]["size"] == max(r["size"] for r in style["runs"] if r["page"] == 1 and not r["icon"])


def test_a_second_read_of_the_same_file_asks_nothing(read):
    read("latex-classic")
    before = len(read.calls)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(style_structure, "_cache_dir", lambda: read.home / "cache")
        mp.setattr(style_structure, "_ask", lambda text, feature="style": pytest.fail("a second call"))
        style_structure.structure_for(STYLES / "latex-classic.pdf")
    assert len(read.calls) == before


@pytest.mark.parametrize("name", RERUNS)
def test_a_rerun_of_the_model_finds_the_same_headings(read, name, tmp_path):
    """The heading set is stable across calls (a heading's column and kind are worked out in code, not asked)."""
    first = sorted(h["text"] for h in read(name)["headings"])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(style_structure, "_cache_dir", lambda: tmp_path / "again")
        again = style_extract.extract(STYLES / f"{name}.pdf", structure=style_structure.structure_for(STYLES / f"{name}.pdf"))
    assert sorted(h["text"] for h in again["headings"]) == first
