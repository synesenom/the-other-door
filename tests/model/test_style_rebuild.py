"""The CV style rebuild (#149) with the real stylist agent on the local claude's plan (#238).

Not in the offline suite or CI (marker `model`): `./scripts/run-test.sh --model`, before a release. Each case is one
`style_build.build` as the app's build runs it: the real model, the real pinned Chromium, the fonts fetched from
google/fonts. The cases: every CV of the style corpus that has a style to copy (the real, scrubbed ones and the made-up
designs; a new one is picked up from expected.json), each with the example CV as the user's, and the edges: the fonts
unreachable, a user's CV far shorter or far longer than the one whose look is copied. A build whose best round stays
under `style_compare.FLOOR` fails and writes nothing; a ready one's style is then chosen and previewed, as the app does,
and that print is read back: its columns, and what an ATS reads of it. Every check is on behaviour, never on the model's
HTML. A CV with nothing to copy (a scan, a LinkedIn export, three columns) stops before the model and is tested offline
(`tests/tailoring/test_style_build_loop.py`). A build takes 2-5 minutes (all seven rounds when no draft comes close).

A case a known issue still breaks is an `xfail` naming it: the release gate stays green, and a pass shows as XPASS.
"""

import json
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from conftest import claude_ready
from style_build_utils import EXAMPLE, STYLES

from door.commands import compile as compile_cmd
from door.commands import style as style_cmd
from door.core import chromium, fonts, workspace
from door.tailoring import cv_body, readability, style_build, style_compare, style_extract

pytestmark = [pytest.mark.model, pytest.mark.real_chromium]

EXPECTED = json.loads((STYLES / "expected.json").read_text(encoding="utf-8"))
EXAMPLE_CV = (EXAMPLE / "cv.md").read_text(encoding="utf-8")

SHORT_CV = """# Sam Example

**Email:** sam@example.com | **Location:** Copenhagen

## Work Experience

### Junior Analyst | Example Co — 2023 - present

- Prepared the weekly sales report.

## Education

### BSc in Economics | Example University — 2023
"""


def _long_cv() -> str:
    """The example CV with eight more jobs: three pages or more."""
    more = "".join(f"\n### Analyst {n} | Example Firm {n} — {2000 + n} - {2001 + n}\n\n"
                   + "".join(f"- Ran the {w} close and wrote the {w} report for the board.\n"
                             for w in ("monthly", "quarterly", "yearly"))
                   for n in range(8))
    head, tail = EXAMPLE_CV.split("## Education", 1)
    return head.rstrip("\n") + "\n" + more + "\n## Education" + tail


def _no_fonts(plan, dest):
    raise fonts.FontsError("google/fonts unreachable (the test's stand-in)")


class Case(NamedTuple):
    pdf: str
    cv_md: str = EXAMPLE_CV
    fonts_fetch: Callable | None = None
    columns: int | None = None  # the columns of the chosen style's print; None: the original's


CASES = {
    **{stem: Case(stem) for stem in sorted(EXPECTED) if EXPECTED[stem]["verdict"]["copyable"]},
    # no free font at all: the build still works with the shipped ones and the generic families
    "fonts-unreachable": Case("scrubbed-pages-header-en", fonts_fetch=_no_fonts),
    # none of a side column's sections (skills, languages, interests) in the user's CV: the side band holds only the photo
    "short-cv-two-columns": Case("scrubbed-pages-sidebar-fr", cv_md=SHORT_CV, columns=1),
    "long-cv-one-column": Case("latex-classic", cv_md=_long_cv()),
    "long-cv-two-columns": Case("latex-sidebar", cv_md=_long_cv()),
}

# the cases a known issue keeps from looking like their original
KNOWN: dict[str, str] = {}  # scrubbed-pages-sidebar-fr came off with #262: best 0.745 in a real run, its photo in place


def _ready() -> str | None:
    """Why a real build cannot happen here, or None."""
    if reason := claude_ready():
        return reason
    if chromium.find_chromium() is None:
        return "no pinned Chromium (./door doctor --fix)"
    try:
        urllib.request.urlopen(urllib.request.Request("https://raw.githubusercontent.com/", method="HEAD"), timeout=10)
    except urllib.error.HTTPError:
        pass  # an answer: the host is reachable
    except OSError:
        return "google/fonts (raw.githubusercontent.com) is unreachable"
    return None


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    """Each case built once, when a test first asks: name -> (result, home), the profile in home/profile."""
    if reason := _ready():
        pytest.skip(reason)
    done: dict[str, tuple[dict, Path]] = {}

    def build(name: str) -> tuple[dict, Path]:
        if name not in done:
            case, home = CASES[name], tmp_path_factory.mktemp(name)
            (home / "profile").mkdir()
            (home / "profile" / "cv.md").write_text(case.cv_md, encoding="utf-8")
            result = style_build.build(STYLES / f"{case.pdf}.pdf", work_dir=home / "work", profile_dir=home / "profile",
                                       fonts_fetch=case.fonts_fetch)
            print(f"\n{name}: {result['state']} in {result['rounds']} rounds, scores "
                  f"{[round(s, 3) for s in result['scores']]}, fonts "
                  f"{[(f['family'], f['source'], f['resolved']) for f in result['fonts']]} {result['problems']}")
            done[name] = result, home
        return done[name]

    return build


@pytest.fixture(scope="module")
def chosen(builds):
    """A ready case's style chosen ("Use the style of my CV") and previewed, as the app does: name -> (the print of
    the user's CV in it, the body as that print places it)."""
    done: dict[str, tuple[Path, str]] = {}

    def choose(name: str) -> tuple[Path, str]:
        result, home = builds(name)
        if result["state"] != "ready":
            pytest.skip(f"not built: {result['problems']}")
        if name not in done:
            profile = home / "profile"
            shutil.copyfile(EXAMPLE / "config.json", profile / "config.json")
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(workspace, "HOME", home)
                assert style_cmd._use_core("like", profile_dir=profile)["in_use"] == "like"
                like = style_cmd._show_core(home=home, profile_dir=profile)["styles"]["like"]
                assert like["cv"] and like["letter"]
                assert all(Path(p).is_file() for p in like["cv"] + like["letter"])
                config = json.loads((profile / "config.json").read_text(encoding="utf-8"))
                placed = compile_cmd.placed_cv(cv_body.body(CASES[name].cv_md), config)
            done[name] = home / ".style" / "preview" / "like" / "cv.pdf", placed
        return done[name]

    return choose


def _known(names):
    """`names` as parameters, a case a known issue breaks an xfail naming it."""
    return [pytest.param(n, marks=pytest.mark.xfail(reason=f"known: {KNOWN[n]}", strict=False)) if n in KNOWN else n
            for n in names]


# a build under the floor fails (#241): a case a known issue keeps from looking like its original is not ready either
@pytest.mark.parametrize("name", _known(n for n in CASES if CASES[n].fonts_fetch is None))
def test_the_build_is_ready(builds, name):
    result, _ = builds(name)
    assert result["state"] == "ready", (result["problems"], result["scores"])


# fonts-unreachable is left out: with no free font to print with, it is not meant to look like the original
@pytest.mark.parametrize("name", [n for n in CASES if CASES[n].fonts_fetch is None])
def test_the_cvs_main_font_has_a_free_stand_in(builds, name):
    result, _ = builds(name)
    assert result["font_error"] is None
    main = next(iter(EXPECTED[CASES[name].pdf]["fonts"])).casefold()
    entry = next((f for f in result["fonts"] if f["family"].casefold() == main), None)
    assert entry and entry["source"] != "none", result["fonts"]


def test_with_the_fonts_unreachable_the_build_says_why_and_is_ready_only_when_it_reaches_the_floor(builds):
    result, _ = builds("fonts-unreachable")
    assert "unreachable" in (result["font_error"] or "")
    if result["scores"] and max(result["scores"]) >= style_compare.FLOOR:
        assert result["state"] == "ready", result["problems"]
    else:
        assert result["state"] == "failed" and result["problems"][0].startswith("the fonts could not be downloaded")


@pytest.mark.parametrize("name", CASES)
def test_the_candidate_has_its_files(builds, name):
    result, home = builds(name)
    if result["state"] != "ready":
        pytest.skip(f"not built: {result['problems']}")
    for file in ("cv.template.html", "cover-letter.template.html", "template.json", "source.pdf"):
        assert (home / "profile" / "style.next" / file).is_file(), file


def _heading_columns(pdf: Path) -> int:
    """How many columns a print's section headings stand in: groups of their left edges more than a sixth of the page
    apart. (`style_extract`'s column bands need a side column of many lines; a user's may have a few.)"""
    style = style_extract.extract(pdf)
    lefts = sorted({round(h["bbox"][0]) for h in style["headings"]})
    gap = style["page"]["size"][0] / 6
    return 1 + sum(1 for a, b in zip(lefts, lefts[1:]) if b - a > gap) if lefts else 0


@pytest.mark.parametrize("name", CASES)
def test_the_chosen_style_prints_the_users_cv_in_the_originals_columns(chosen, name):
    pdf, _ = chosen(name)
    case = CASES[name]
    assert _heading_columns(pdf) == (case.columns or EXPECTED[case.pdf]["columns"])


@pytest.mark.parametrize("name", CASES)
def test_an_ats_reads_the_chosen_styles_print_whole_and_in_order(chosen, name):
    """Name, headings on their own line and in order, no text lost off the page: what `prepare` checks a tailored CV
    for. A nearly empty last page (`sparse`) is only reported there too."""
    pdf, placed = chosen(name)
    person = CASES[name].cv_md.splitlines()[0].removeprefix("# ")
    problems = [p for p in readability.check_pdf(pdf, placed, person, cv=True) if p["kind"] != "sparse"]
    assert not problems, problems
