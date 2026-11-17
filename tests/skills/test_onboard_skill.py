"""/onboard, run by the real model on the local plan against the app's test world (#33).

Not in the offline suite or CI (marker `skills`): `./scripts/run-test.sh --skills`, before a release. The
conversation is real; the server is the test world's (boot.py), its own model calls the stand-in claude;
the user is a small model playing the persona (`skill_run.py`). Every check is on behaviour: which tools,
in which order, what was written and when, never on the model's wording.
"""

import json
from pathlib import Path

import pytest

from conftest import home as _home_of
from conftest import run_skill

pytestmark = pytest.mark.skills

DISCOVERY_KEYS = ("linkedin_discovery", "profession_discovery", "jobbsafari_discovery", "hellowork_discovery")


@pytest.fixture(scope="module")
def onboarded(tmp_path_factory):
    """One /onboard of mette, start to finish: the world, the run's result, its transcript folder."""
    return run_skill(tmp_path_factory, "onboard", "/onboard", empty=True)


def _home(world) -> Path:
    return _home_of(world)


def _order(result) -> list[str]:
    return result["tools"]


def test_it_reads_the_sources_through_the_tools_before_anything_else(onboarded):
    _, result = onboarded
    tools = _order(result)
    assert "draft_cv" in tools and "infer_basics" in tools, tools
    assert tools.index("draft_cv") < tools.index("infer_basics") < tools.index("init_profile"), tools


def test_it_never_reads_a_source_itself_nor_runs_a_shell_command(onboarded):
    world, result = onboarded
    source = Path(world["cvFile"]).resolve()
    misused = [u for u in result["used"]
               if u["tool"] in ("Bash", "Write")
               or (u["tool"] == "Read" and Path(u["input"].get("file_path", "")).resolve() == source)]
    assert not misused, misused


def test_it_writes_the_profile_only_after_the_confirmation_then_starts_the_first_run(onboarded):
    world, result = onboarded
    tools = _order(result)
    assert tools.count("init_profile") == 1, tools
    assert tools.index("init_profile") < tools.index("save_cv") < tools.index("find_jobs"), tools
    init_at = next(c["at"] for c in result["calls"] if c["tool"] == "init_profile")
    config = _home(world) / "profile" / "config.json"
    assert config.stat().st_mtime >= init_at - 1
    assert next(c for c in reversed(result["calls"]) if c["tool"] == "find_jobs")["args"].get("skip") == [
        "discover", "follow", "collect"]


def test_the_saved_profile_is_the_persona(onboarded):
    world, _ = onboarded
    persona = world["persona"]
    config = json.loads((_home(world) / "profile" / "config.json").read_text(encoding="utf-8"))
    assert (config["name"], config["email"], config["location"]) == (persona["name"], persona["email"], persona["city"])
    assert sorted(config["languages"]) == sorted(persona["languages"])
    assert persona["roleTargets"][0] in config["role_targets"]
    assert set(config["role_targets"]) <= set(persona["roleTargets"]), config["role_targets"]
    # Asked about (LinkedIn serves Copenhagen) and left off; none turned on.
    assert config.get("linkedin_discovery") is False
    assert not any(config.get(key) for key in DISCOVERY_KEYS), {k: config.get(k) for k in DISCOVERY_KEYS}


def test_the_saved_cv_is_the_confirmed_draft(onboarded):
    world, _ = onboarded
    profile = _home(world) / "profile"
    assert " ".join((profile / "cv.md").read_text(encoding="utf-8").split()) == " ".join(world["persona"]["cv"].split())
    assert not (profile / "cv.draft.md").exists()


# ----------------------------------------------------------------------------- the CV style opt-in (#153)
STYLED_PDF = Path(__file__).resolve().parents[1] / "tailoring" / "fixtures" / "styles" / "latex-classic.pdf"


def _with_a_pdf_cv(world) -> None:
    """The persona's CV is a PDF with a look to copy, in the world's sources folder."""
    target = Path(world["cvFile"]).with_name("persona-cv.pdf")
    target.write_bytes(STYLED_PDF.read_bytes())
    world["cvFile"] = str(target)


def test_no_style_is_offered_for_a_cv_with_no_look_to_copy(onboarded):
    _, result = onboarded
    assert not {"build_style", "show_style", "use_style"} & set(_order(result)), _order(result)


@pytest.fixture(scope="module")
def styled_yes(tmp_path_factory):
    return run_skill(tmp_path_factory, "onboard-style-yes", "/onboard", empty=True, max_turns=16, seed=_with_a_pdf_cv,
                     facts_note="You want the tailored CVs to look like your CV file.")


def test_a_ticked_style_builds_once_with_that_file_after_the_profile_is_saved_and_the_first_run_does_not_wait(styled_yes):
    world, result = styled_yes
    tools = _order(result)
    assert tools.count("build_style") == 1, tools
    assert tools.index("init_profile") < tools.index("save_cv") < tools.index("build_style"), tools
    assert tools.index("build_style") < tools.index("find_jobs"), tools
    assert Path(next(c for c in result["calls"] if c["tool"] == "build_style")["args"]["file"]).name == "persona-cv.pdf"
    assert not {"show_style", "use_style"} & set(tools), tools



@pytest.fixture(scope="module")
def styled_no(tmp_path_factory):
    return run_skill(tmp_path_factory, "onboard-style-no", "/onboard", empty=True, max_turns=16, seed=_with_a_pdf_cv,
                     facts_note="You keep The other door's look for your tailored CVs; you do not want them to look like your CV file.")


def test_a_style_left_off_builds_nothing(styled_no):
    _, result = styled_no
    tools = _order(result)
    assert "find_jobs" in tools, tools
    assert not {"build_style", "show_style", "use_style"} & set(tools), tools
