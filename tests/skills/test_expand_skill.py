"""/expand, run by the real model on the local plan against the app's test world (#33).

Marker `skills`, never CI (`./scripts/run-test.sh --skills`). Two runs of mette's world: one where she
takes the proposals, one where she wants none. Checks are on behaviour: the tools and their order, and
that `profile/cv.md` changes only after the confirmation.
"""

import pytest

from conftest import home, run_skill

pytestmark = pytest.mark.skills

PROMPT = "/expand https://github.example/mkl https://mkl.example/talks"


def _enrich_calls(result):
    return [c for c in result["calls"] if c["tool"] == "enrich"]


def _applies(call) -> bool:
    args = call["args"]
    return bool(args.get("apply") or args.get("all"))


@pytest.fixture(scope="module")
def accepted(tmp_path_factory):
    return run_skill(tmp_path_factory, "expand-accepted", PROMPT, max_turns=6, stop_after_tool="enrich",
                     persona_kind="onboarded",
                     facts_note="You want every proposal the assistant shows added to your CV: pick all of them.")


@pytest.fixture(scope="module")
def declined(tmp_path_factory):
    return run_skill(tmp_path_factory, "expand-declined", PROMPT, max_turns=2, persona_kind="onboarded",
                     stop_after_tool="never",
                     facts_note="You want none of the proposals added to your CV: pick None.")


def test_it_checks_the_profile_then_proposes_before_it_writes_anything(accepted):
    _, result = accepted
    tools = result["tools"]
    assert tools[0] == "doctor" and tools[1] == "enrich", tools
    first = _enrich_calls(result)[0]
    assert not _applies(first), first
    assert first["args"].get("urls") == PROMPT.split()[1:], first


def test_the_cv_changes_only_after_the_user_chose(accepted):
    world, result = accepted
    enriches = _enrich_calls(result)
    assert len(enriches) == 2, result["tools"]
    assert _applies(enriches[1])
    assert result["asked"], "no AskUserQuestion between propose and apply"
    profile = home(world) / "profile"
    assert (profile / "cv.md.bak").exists()
    assert profile.joinpath("cv.md").read_text(encoding="utf-8") != (profile / "cv.md.bak").read_text(encoding="utf-8")
    assert "PyMC" in (profile / "cv.md").read_text(encoding="utf-8")


def test_a_user_who_wants_none_leaves_the_cv_untouched(declined):
    world, result = declined
    enriches = _enrich_calls(result)
    assert len(enriches) == 1 and not _applies(enriches[0]), result["calls"]
    profile = home(world) / "profile"
    assert not (profile / "cv.md.bak").exists()
    assert result["asked"]


def test_it_uses_neither_a_shell_nor_a_file_write(accepted, declined):
    for _, result in (accepted, declined):
        assert not [u for u in result["used"] if u["tool"] in ("Bash", "Write")], result["used"]
