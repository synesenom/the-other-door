"""The CV style rebuild (#149) with the real stylist agent on the local claude's plan (#238).

Not in the offline suite or CI (marker `skills`): `./scripts/run-test.sh --skills`, before a release. Each case is one
`style_build.build` as the app's build runs it: the real model, the real pinned Chromium, the fonts fetched from
google/fonts. The cases: every CV of the style corpus (the real, scrubbed ones and the made-up designs; a new one is
picked up from expected.json), each with the example CV as the user's, the ones with nothing to copy (a scan, a
LinkedIn export) stopping before any model call; and the edges: the fonts unreachable, a user's CV far shorter or far
longer than the one whose look is copied. A ready style is then chosen and previewed, as the app does. Every check is
on behaviour (a ready build, its files, its columns, its score, its previews), never on the model's HTML. A build
takes 2-4 minutes.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from paths import REPO_ROOT, TESTS_DIR

from door.commands import style as style_cmd
from door.core import chromium, fonts, workspace
from door.tailoring import style_build

pytestmark = [pytest.mark.skills, pytest.mark.real_chromium]

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"
EXPECTED = json.loads((STYLES / "expected.json").read_text(encoding="utf-8"))
FLOOR = 0.5  # the best round's blurred score: Sonnet's median was 0.94 in #206, a broken rebuild scores near 0
EXAMPLE_CV = (REPO_ROOT / "profile.example" / "cv.md").read_text(encoding="utf-8")

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
    fonts_fetch: object = None
    side: bool | None = None  # whether the rebuild has a side column; None: as the original


CASES = {
    **{stem: Case(stem) for stem in sorted(EXPECTED)},
    "fonts-unreachable": Case("scrubbed-pages-header-en", fonts_fetch=_no_fonts),
    # none of a side column's sections (skills, languages, interests) in the user's CV: one column
    "short-cv-two-columns": Case("scrubbed-pages-sidebar-fr", cv_md=SHORT_CV, side=False),
    "long-cv-one-column": Case("latex-classic", cv_md=_long_cv()),
}
COPYABLE = [n for n, case in CASES.items() if EXPECTED[case.pdf]["verdict"]["copyable"]]
NOT_COPYABLE = [n for n in CASES if n not in COPYABLE]


def _ready() -> str | None:
    """Why a real build cannot happen here, or None."""
    if not shutil.which("claude"):
        return "no claude on PATH"
    status = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True)
    if status.returncode != 0 or not json.loads(status.stdout or "{}").get("loggedIn"):
        return "claude is not signed in (claude auth login)"
    if chromium.find_chromium() is None:
        return "no pinned Chromium (./door doctor --fix)"
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
                  f"{[round(s, 3) for s in result['scores']]} {result['problems']}")
            done[name] = result, home
        return done[name]

    return build


def _ready_build(builds, name: str) -> Path:
    result, home = builds(name)
    if result["state"] != "ready":
        pytest.skip(f"not built: {result['problems']}")
    return home


@pytest.mark.parametrize("name", COPYABLE)
def test_the_build_is_ready(builds, name):
    result, _ = builds(name)
    assert result["state"] == "ready", result["problems"]


@pytest.mark.parametrize("name", COPYABLE)
def test_the_best_round_looks_like_the_original(builds, name):
    result, _ = builds(name)
    assert result["scores"] and max(result["scores"]) >= FLOOR, result["scores"]


@pytest.mark.parametrize("name", [n for n in COPYABLE if CASES[n].fonts_fetch is None])
def test_the_fonts_were_fetched(builds, name):
    result, _ = builds(name)
    assert result["font_error"] is None and result["fonts"]


def test_with_the_fonts_unreachable_the_shipped_ones_stand_in(builds):
    result, _ = builds("fonts-unreachable")
    assert "unreachable" in (result["font_error"] or "")


@pytest.mark.parametrize("name", COPYABLE)
def test_the_candidate_has_its_files_and_keeps_the_originals_columns(builds, name):
    folder = _ready_build(builds, name) / "profile" / "style.next"
    for file in ("cv.template.html", "cover-letter.template.html", "template.json", "source.pdf"):
        assert (folder / file).is_file(), file
    case = CASES[name]
    side = EXPECTED[case.pdf]["columns"] == 2 if case.side is None else case.side
    columns = json.loads((folder / "template.json").read_text(encoding="utf-8")).get("columns") or {}
    assert bool(columns.get("side")) is side, columns


@pytest.mark.parametrize("name", COPYABLE)
def test_the_rebuilt_style_once_chosen_previews_the_cv_and_the_letter(builds, name, monkeypatch):
    home = _ready_build(builds, name)
    profile = home / "profile"
    monkeypatch.setattr(workspace, "HOME", home)
    shutil.copyfile(REPO_ROOT / "profile.example" / "config.json", profile / "config.json")
    assert style_cmd._use_core("like", profile_dir=profile)["in_use"] == "like"
    like = style_cmd._show_core(home=home, profile_dir=profile)["styles"]["like"]
    assert like["cv"] and like["letter"]
    assert all(Path(p).is_file() for p in like["cv"] + like["letter"])


@pytest.mark.parametrize("name", NOT_COPYABLE)
def test_a_cv_with_nothing_to_copy_stops_before_the_model_and_writes_nothing(builds, name):
    result, home = builds(name)
    assert result["state"] == "failed" and result["rounds"] == 0 and result["problems"]
    assert not (home / "profile" / "style.next").exists()
