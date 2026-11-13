"""`init`: interactive profile bootstrap.

Split out of the former tests/test_door_cli.py (issue #15 onward); the shared
`cli_env` fixture is in tests/commands/conftest.py, helpers in tests/cli_utils.py.
"""

import json
import shutil
import types

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.core import workspace
import door.core.profile_loader as profile_loader
from cli_utils import result_text
from paths import REPO_ROOT


# --------------------------------------------------------------------------- #
# init (issue #74)
# --------------------------------------------------------------------------- #

from door.commands import profile as profile_cmd

# The "Other…" choice of the location list.
OTHER = profile_cmd.OTHER_LOCATION

# Reading the sources finds all of this in the stubs below, so a test starts at the review.
_JANE = dict(cv_sources="old-cv.pdf")
_CV = "# Jane Doe\n\n**Email:** jane@x.com | **Location:** Copenhagen\n\nMY DRAFTED CV\n"


_REAL_PROFILE_EXAMPLE_DIR = REPO_ROOT / "profile.example"


@pytest.fixture
def init_env(tmp_path, monkeypatch):
    """Redirect The other door's PROFILE_DIR/PROFILE_EXAMPLE_DIR into tmp_path.

    Copies the real, committed profile.example/ tree into
    tmp_path/profile.example and rewrites the three template path fields in
    its config.json to absolute paths pointing at the copied files, so
    `Profile.model_validate` (which resolves relative template paths against
    the real project root) succeeds against files that actually exist under
    tmp_path — independent of the dev machine's real profile/ directory.

    No profile/ directory is created here — tests exercise `init`'s
    fresh-bootstrap and existing-profile branches explicitly.
    """
    example_dir = tmp_path / "profile.example"
    shutil.copytree(_REAL_PROFILE_EXAMPLE_DIR, example_dir)

    config_path = example_dir / "config.json"
    config = json.loads(config_path.read_text())
    for field, filename in (
        ("cv_template", "cv.template.tex"),
        ("cv_content", "cv.md"),
        ("cover_letter_template", "cover-letter.template.tex"),
    ):
        config[field] = str(example_dir / filename)
    config_path.write_text(json.dumps(config))

    profile_dir = tmp_path / "profile"

    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", example_dir)

    return types.SimpleNamespace(profile_dir=profile_dir, example_dir=example_dir)


@pytest.fixture(autouse=True)
def wizard_calls(monkeypatch, prompts):
    """The wizard's steps reach outside: `claude -p`, a real run, `claude auth status`.
    None of that may happen here by accident: the first run fails the test unless the test patches it itself;
    the draft, the basics, the titles and the search terms are stubbed and recorded; Claude is signed in."""
    from door.commands import cv as cv_cmd
    from door.commands import keywords as keywords_cmd
    from door.commands import find as find_cmd
    from door.commands import preview as preview_cmd
    from door.commands import titles as titles_cmd
    from door.core import doctor, installers

    calls = types.SimpleNamespace(keywords=[], drafts=[], basics=_basics(), look={"board": "jobindex", "matches": []}, titles=[
        {"title": "Data Scientist", "reason": "your latest title", "recommended": True},
        {"title": "ML Lead", "reason": "you led a team", "recommended": True},
        {"title": "Quant", "reason": "maths", "recommended": False},
    ], titles_warning=None)

    def _refuse(*a, **k):
        pytest.fail("init's wizard reached the real run; stub it in the test")

    def canned_keywords(targets=None, **k):
        calls.keywords.append(list(targets or []))
        return {"role_targets": targets, "keywords": ["data scientist", "ml engineer"],
                "topic_terms": ["data", "machine learning"], "saved": False}

    def canned_draft(sources, *, profile_dir, **kw):
        calls.drafts.append(list(sources))
        profile_dir.mkdir(parents=True, exist_ok=True)
        path = profile_dir / "cv.draft.md"
        path.write_text(_CV)
        return {"draft_path": str(path), "written": False, "sources": [],
                "provenance": [{"source": "github", "contributed": "two projects"}], "todos": ["phone number"]}

    def canned_titles(titles=None, **k):
        result = {"titles": calls.titles}
        return {**result, "warning": calls.titles_warning} if calls.titles_warning else result

    monkeypatch.setattr(find_cmd, "_find_core", _refuse)
    monkeypatch.setattr(cv_cmd, "_draft_cv_core", canned_draft)
    monkeypatch.setattr(cv_cmd, "_infer_basics_core", lambda *a, **k: dict(calls.basics))
    monkeypatch.setattr(titles_cmd, "_titles_core", canned_titles)
    monkeypatch.setattr(keywords_cmd, "_keywords_core", canned_keywords)
    monkeypatch.setattr(preview_cmd, "_preview_core", lambda config, cv, **k: dict(calls.look, config=config, cv=cv))
    monkeypatch.setattr(doctor, "check_claude_cli", lambda *a, **k: {"status": "ok"})
    monkeypatch.setattr(doctor, "check_claude_login", lambda *a, **k: {"status": "ok"})
    monkeypatch.setattr(installers, "find_claude", lambda *a, **k: "/bin/claude")
    return calls


def _basics(**fields):
    return {"name": "Jane Doe", "email": "jane@x.com", "location": "Copenhagen", "languages": ["English"],
            "remote": "hybrid", "missing": [], **fields}


def _stop_at_first_run(monkeypatch):
    from door.commands import find as find_cmd

    seen = {}

    def fake(step=None, **kw):
        seen.update(kw, step=step)
        raise ValueError("stop here")  # `find` renders it and exits; enough to see what it was asked
    monkeypatch.setattr(find_cmd, "_find_core", fake)
    return seen


def _config(init_env):
    return json.loads((init_env.profile_dir / "config.json").read_text())


def _invoke(*args):
    result = CliRunner().invoke(cli, ["init", *args])
    assert result.exit_code == 0, result_text(result)
    return result


def test_init_with_a_good_cv_asks_nothing_before_the_review(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    assert prompts.order == ["cv_sources", "preferences", "titles_pick", "titles_add", "discovery_pick", "photo", "review"]


def test_init_fresh_saves_every_key_of_the_review(init_env, prompts, monkeypatch):
    """Nothing of the example config survives a fresh home."""
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    data = _config(init_env)
    profile = profile_loader.Profile.model_validate(data)
    assert (profile.name, profile.email, profile.location) == ("Jane Doe", "jane@x.com", "Copenhagen")
    assert profile.role_targets == ["Data Scientist", "ML Lead"]  # the recommended titles
    assert data["search_keywords"] == ["data scientist", "ml engineer"]
    assert data["topic_terms"] == ["data", "machine learning"]
    assert data["languages"] == ["English"] and data["remote"] == "hybrid"
    assert data["exclude"] == {"companies": [], "keywords": []}
    assert "boards" not in data
    assert (init_env.profile_dir / "cv.md").read_text() == _CV
    assert not (init_env.profile_dir / "cv.md.bak").exists()  # no example CV was put there to replace
    assert not (init_env.profile_dir / "cv.draft.md").exists()


def test_init_writes_nothing_before_the_review_is_saved(init_env, prompts, monkeypatch):
    seen = []
    real = profile_cmd._save_answers
    monkeypatch.setattr(profile_cmd, "_save_answers", lambda a: seen.append((init_env.profile_dir / "config.json").exists()) or real(a))
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    assert seen == [False]


def test_save_starts_the_first_run_at_once(init_env, prompts, monkeypatch):
    seen = _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    assert seen["step"] is None and seen["skip"] == ["discover", "follow", "collect"]
    assert "first_run" not in prompts.order


def test_no_sources_asks_for_everything_and_runs_nothing(init_env, prompts, wizard_calls):
    wizard_calls.basics = _basics(name=None, email=None, location=None, missing=["name", "email", "location"])
    wizard_calls.titles = []
    wizard_calls.titles_warning = "no CV of yours to suggest titles from yet"
    prompts.answers.update(name="Jane Doe", email="jane@x.com", location="Aarhus", role_targets="Analyst, Quant")
    result = _invoke()
    assert wizard_calls.drafts == []
    assert [n for n in prompts.order if n in ("name", "email", "location", "role_targets")] == ["name", "email", "location", "role_targets"]
    data = _config(init_env)
    assert data["location"] == "Aarhus" and data["role_targets"] == ["Analyst", "Quant"]
    assert wizard_calls.keywords == [["Analyst", "Quant"]]
    assert "still the example" in result_text(result)


@pytest.mark.parametrize("key,answer", [("name", "Jane Doe"), ("email", "jane@x.com"), ("location", "Odense")])
def test_each_missing_value_is_exactly_one_question(init_env, prompts, wizard_calls, monkeypatch, key, answer):
    _stop_at_first_run(monkeypatch)
    wizard_calls.basics = _basics(**{key: None, "missing": [key]})
    prompts.answers.update(_JANE, **{key: answer})
    CliRunner().invoke(cli, ["init"])
    assert prompts.order.count(key) == 1
    assert prompts.order.index(key) < prompts.order.index("review")
    assert not {"name", "email", "location"} - {key} & set(prompts.order)
    assert _config(init_env)[key] == answer


def test_a_city_not_covered_says_so_and_asks(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    wizard_calls.basics = _basics(location=None, unsupported_location="Berlin, Germany", missing=["location"])
    prompts.answers.update(_JANE, location=OTHER, location_other="Berlin")
    result = CliRunner().invoke(cli, ["init"])
    assert "Berlin, Germany" in result_text(result)
    assert prompts.asked["location_other"]["default"] == "Berlin, Germany"
    assert _config(init_env)["location"] == "Berlin"


def test_a_failed_titles_call_falls_back_to_asking_for_them(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    wizard_calls.titles, wizard_calls.titles_warning = [], "not logged in"
    prompts.answers.update(_JANE, role_targets="Analyst")
    result = CliRunner().invoke(cli, ["init"])
    assert "not logged in" in result_text(result)
    assert _config(init_env)["role_targets"] == ["Analyst"]


def test_the_first_look_shows_scored_ads_after_reading_and_before_the_review(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    wizard_calls.look = {"board": "jobindex", "matches": [
        {"title": "Lead Analyst", "company": "Acme", "location": "Copenhagen", "score": 0.8, "score_reason": "your SQL", "url": "u"},
    ]}
    prompts.answers.update(_JANE)
    text = result_text(CliRunner().invoke(cli, ["init"]))
    assert "A first look" in text and "Lead Analyst at Acme: your SQL" in text


def test_the_first_look_failing_is_one_line(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    wizard_calls.look = {"board": "jobindex", "matches": [], "warning": "no first look this time"}
    prompts.answers.update(_JANE)
    assert "no first look this time" in result_text(CliRunner().invoke(cli, ["init"]))
    assert _config(init_env)["name"] == "Jane Doe"


def test_titles_are_listed_with_reasons_and_only_the_recommended_are_ticked(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    asked = prompts.asked["titles_pick"]
    assert asked["choices"][0] == ("Data Scientist: your latest title", "Data Scientist")
    assert asked["default"] == ["Data Scientist", "ML Lead"]


def test_changing_the_titles_proposes_the_search_terms_again(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, titles_pick=["Quant"], titles_add="Actuary, Quant")
    CliRunner().invoke(cli, ["init"])
    assert wizard_calls.keywords == [["Data Scientist", "ML Lead"], ["Quant", "Actuary"]]
    assert _config(init_env)["role_targets"] == ["Quant", "Actuary"]


def test_keeping_the_titles_proposes_nothing_again(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    assert len(wizard_calls.keywords) == 1


def test_a_failed_terms_call_searches_the_titles_as_they_are(init_env, prompts, monkeypatch):
    from door.commands import keywords as keywords_cmd
    from door.core import claude_cli

    def boom(*a, **k):
        raise claude_cli.ClaudeError("not logged in")

    monkeypatch.setattr(keywords_cmd, "_keywords_core", boom)
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    result = CliRunner().invoke(cli, ["init"])
    assert "not logged in" in result_text(result)
    assert _config(init_env)["search_keywords"] == ["Data Scientist", "ML Lead"]


def test_discovery_is_off_unless_ticked_and_saved_either_way(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, discovery_pick=["linkedin_discovery"])
    CliRunner().invoke(cli, ["init"])
    asked = prompts.asked["discovery_pick"]
    assert asked["default"] == [] and "LinkedIn" in asked["message"] and "LEGAL_DISCLAIMER.md" in asked["message"]
    assert [key for _, key in asked["choices"]] == ["linkedin_discovery"]  # profession.hu is Hungary only
    data = _config(init_env)
    assert data["linkedin_discovery"] is True
    assert "profession_discovery" not in data


def test_pressing_enter_through_the_review_turns_no_discovery_source_on(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    data = _config(init_env)
    assert data["linkedin_discovery"] is False


def test_changing_the_city_asks_about_its_discovery_sources(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, review=iter(["location", "save"]), location="Budapest")
    CliRunner().invoke(cli, ["init"])
    data = _config(init_env)
    assert data["location"] == "Budapest" and data["profession_discovery"] is False


def test_the_review_can_change_every_value(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(
        _JANE,
        review=iter(["name", "email", "remote", "languages", "search_keywords", "topic_terms", "save"]),
        name=iter(["New Name"]), email=iter(["new@x.com"]), remote="yes", languages=["English", "Danish"],
        search_keywords_pick=["ml engineer"], search_keywords_add="mlops", topic_terms_pick=["data"], topic_terms_add="",
    )
    CliRunner().invoke(cli, ["init"])
    data = _config(init_env)
    assert (data["name"], data["email"], data["remote"]) == ("New Name", "new@x.com", "yes")
    assert data["languages"] == ["English", "Danish"]
    assert data["search_keywords"] == ["ml engineer", "mlops"] and data["topic_terms"] == ["data"]


def test_the_review_shows_the_drafts_provenance_and_todos(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    text = result_text(CliRunner().invoke(cli, ["init"]))
    assert "github: two projects" in text and "TODO: phone number" in text


def test_the_review_can_open_the_draft_in_an_editor(init_env, prompts, monkeypatch):
    import click
    from pathlib import Path

    _stop_at_first_run(monkeypatch)
    monkeypatch.setattr(click, "edit", lambda filename=None, **kw: Path(filename).write_text("EDITED CV\n"))
    prompts.answers.update(_JANE, review=iter(["cv", "save"]))
    CliRunner().invoke(cli, ["init"])
    assert (init_env.profile_dir / "cv.md").read_text() == "EDITED CV\n"


def test_a_value_the_profile_refuses_goes_back_to_the_review(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, titles_pick=iter([[], ["Quant"]]), review=iter(["save", "titles", "save"]))
    result = CliRunner().invoke(cli, ["init"])
    assert "role_targets" in result_text(result)
    assert _config(init_env)["role_targets"] == ["Quant"]


def test_init_asks_again_after_a_bad_source(init_env, prompts, monkeypatch):
    from door.commands import cv as cv_cmd

    def draft(sources, *, profile_dir, **kw):
        raise FileNotFoundError(f"no such file: {sources[0]}")

    monkeypatch.setattr(cv_cmd, "_draft_cv_core", draft)
    prompts.answers.update(cv_sources=iter(["missing.pdf", ""]), name="J", email="j@x.com", location="Aarhus")
    result = _invoke()
    assert "no such file: missing.pdf" in result_text(result)
    assert "No sources" in result_text(result)


def test_public_pages_are_kept_for_enrich_but_not_linkedin(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(cv_sources="old-cv.pdf, https://github.com/jane, https://www.linkedin.com/in/jane")
    CliRunner().invoke(cli, ["init"])
    assert _config(init_env)["enrich_sources"] == ["https://github.com/jane"]


def test_a_missing_claude_interrupts_and_can_be_declined(init_env, prompts, monkeypatch):
    from door.core import doctor, installers

    monkeypatch.setattr(doctor, "check_claude_cli", lambda *a, **k: {"status": "missing"})
    monkeypatch.setattr(installers, "find_claude", lambda *a, **k: None)
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, claude_install=False)
    CliRunner().invoke(cli, ["init"])
    assert prompts.order.index("cv_sources") < prompts.order.index("claude_install") < prompts.order.index("review")


def test_a_missing_claude_is_installed_on_a_yes(init_env, prompts, monkeypatch):
    from door.commands import setup as setup_cmd
    from door.core import doctor

    installed = []
    monkeypatch.setattr(doctor, "check_claude_cli", lambda *a, **k: {"status": "missing"})
    monkeypatch.setattr(setup_cmd, "_setup_core", lambda **kw: installed.append(kw) or {})
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, claude_install=True)
    CliRunner().invoke(cli, ["init"])
    assert installed == [{"install": ["claude"], "yes": True, "interactive": True}]


def test_signing_in_interrupts_only_when_signed_out(init_env, prompts, monkeypatch):
    from door.core import doctor

    statuses = iter([{"status": "missing", "fix": "claude auth login"}, {"status": "ok"}])
    monkeypatch.setattr(doctor, "check_claude_login", lambda *a, **k: next(statuses))
    signed_in = []
    monkeypatch.setattr(profile_cmd, "_sign_in", signed_in.append)
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    assert prompts.order.count("claude_login") == 1 and signed_in == ["/bin/claude"]


def test_declining_the_sign_in_goes_on_and_warns(init_env, prompts, monkeypatch):
    from door.core import doctor

    monkeypatch.setattr(doctor, "check_claude_login", lambda *a, **k: {"status": "missing", "fix": "claude auth login"})
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, claude_login=False)
    result = CliRunner().invoke(cli, ["init"])
    assert "claude auth login" in result_text(result) and "review" in prompts.order


def test_init_never_asks_for_exclusions_or_a_score(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    assert not {"exclude_companies", "exclude_keywords", "min_score"} & set(prompts.order)


def test_init_location_is_picked_from_the_known_cities(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    wizard_calls.basics = _basics(location=None, missing=["location"])
    prompts.answers.update(_JANE, location="Aarhus")
    CliRunner().invoke(cli, ["init"])
    asked = prompts.asked["location"]
    assert asked["kind"] == "select" and ("Copenhagen (Denmark)", "Copenhagen") in asked["choices"]
    assert asked["choices"][-1] == (OTHER, OTHER)


def test_init_says_which_boards_are_searched(init_env, prompts, monkeypatch, country_boards):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    text = result_text(CliRunner().invoke(cli, ["init"]))
    assert "jobindex" in text and "thehub" in text
    assert "boards" not in prompts.order


def test_a_city_in_no_known_country_says_only_the_worldwide_boards_are_searched(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    wizard_calls.basics = _basics(location="Berlin")
    prompts.answers.update(_JANE)
    text = result_text(CliRunner().invoke(cli, ["init"]))
    assert "isn't in a supported country" in text and "docs/adding-a-site.md" in text


def test_a_known_city_prints_no_add_a_country_note(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    assert "adding-a-site" not in result_text(CliRunner().invoke(cli, ["init"]))


def test_the_review_offers_the_supported_job_ad_languages(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, review=iter(["languages", "save"]), languages=["English"])
    CliRunner().invoke(cli, ["init"])
    assert [c[0] for c in prompts.asked["languages"]["choices"]] == ["English", "Danish", "French", "Hungarian", "Swedish"]
    assert prompts.asked["languages"]["validate"]([]) is not None


def test_init_keeps_the_employers_already_followed(init_env, prompts):
    """Re-running init on a profile that follows employers leaves the list alone, and no note is printed."""
    from door.core import companies

    _write_existing_profile_config(init_env)
    companies.save(init_env.profile_dir, [companies.Company(
        name="Stripe", feed=companies.Feed(platform="greenhouse", id="stripe"), status="followed", found_via="manual")])
    prompts.answers.update(steps=["details"])

    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)

    assert companies.feed_entries(init_env.profile_dir, "greenhouse") == ["stripe"]
    assert "companies add" not in result_text(result)


def _write_existing_profile_config(init_env, **overrides) -> dict:
    """Seed init_env.profile_dir/config.json with a valid, Profile-loadable config.

    Reuses the (already-absolute-templated) profile.example/config.json as a
    base so `Profile.model_validate` succeeds without needing to duplicate
    template files under profile/.
    """
    base = json.loads((init_env.example_dir / "config.json").read_text())
    base.update(overrides)
    init_env.profile_dir.mkdir(parents=True, exist_ok=True)
    (init_env.profile_dir / "config.json").write_text(json.dumps(base))
    return base


def test_init_existing_profile_declined_leaves_config_untouched(init_env, prompts):
    """Picking no step leaves profile/config.json untouched."""
    _write_existing_profile_config(init_env, name="Existing User")
    prompts.answers.update(steps=[])

    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert "left unchanged" in result_text(result)

    data = json.loads((init_env.profile_dir / "config.json").read_text())
    assert data["name"] == "Existing User"


def test_init_existing_profile_confirmed_reuses_existing_values(init_env, prompts):
    """Redoing the details keeps unprompted fields and doesn't clobber cv.md."""
    _write_existing_profile_config(
        init_env,
        name="Existing User",
        role_targets=["Old Role"],
        remote="hybrid",
    )
    (init_env.profile_dir / "cv.md").write_text("MY REAL CV")

    # redo the review; accept every default except location -> "Aarhus"
    prompts.answers.update(steps=["review"], review=iter(["location", "save"]), location="Aarhus")
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)

    data = json.loads((init_env.profile_dir / "config.json").read_text())
    assert data["role_targets"] == ["Old Role"]
    assert data["remote"] == "hybrid"
    assert data["location"] == "Aarhus"

    assert (init_env.profile_dir / "cv.md").read_text() == "MY REAL CV"


def test_init_partial_profile_dir_copies_missing_files_only(init_env, prompts):
    """profile/ exists but has no config.json (e.g. only some notes) — init fills it in."""
    state_dir = init_env.profile_dir / "notes"
    state_dir.mkdir(parents=True)
    (state_dir / "mine.json").write_text('{"notes": []}')

    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)

    config_path = init_env.profile_dir / "config.json"
    assert config_path.exists()
    profile_loader.Profile.model_validate(json.loads(config_path.read_text()))

    assert (init_env.profile_dir / "cv.template.tex").exists()
    assert not (init_env.profile_dir / "cv.md").exists()  # no CV yet, not the example's
    assert (state_dir / "mine.json").read_text() == '{"notes": []}'


def test_init_never_copies_the_example_story_bank(init_env, prompts):
    """profile.example/story_bank.md is made-up stories; the tailor reads
    profile/story_bank.md as the candidate's own, so init must not copy it."""
    assert (init_env.example_dir / "story_bank.md").exists()

    result = CliRunner().invoke(cli, ["init", *_FLAGS])
    assert result.exit_code == 0, result_text(result)

    assert not (init_env.profile_dir / "story_bank.md").exists()


# --------------------------------------------------------------------------- #
# init with flags: the non-interactive half, the same fields as `init_profile`
# --------------------------------------------------------------------------- #

_FLAGS = [
    "--name", "Jane Doe", "--email", "jane@x.com", "--location", "Copenhagen",
    "--role-targets", "Data Scientist, ML Lead",
    "--min-score", "0.7", "--languages", "English, Danish",
]


def test_init_with_flags_asks_nothing_and_writes(init_env, prompts):
    result = CliRunner().invoke(cli, ["init", *_FLAGS])
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == []

    data = json.loads((init_env.profile_dir / "config.json").read_text())
    assert data["name"] == "Jane Doe"
    assert data["role_targets"] == ["Data Scientist", "ML Lead"]
    assert data["min_score"] == 0.7
    assert data["languages"] == ["English", "Danish"]
    assert not (init_env.profile_dir / "cv.md").exists()  # no CV yet, not the example's
    assert "Wrote" in result_text(result)


def test_init_with_flags_updates_an_existing_profile_in_place(init_env, prompts):
    """A flag on an existing profile changes only that key — no overwrite question,
    like the `init_profile` tool ("expand my search keywords" from a shell)."""
    _write_existing_profile_config(init_env, name="Existing User", role_targets=["Old Role"])
    (init_env.profile_dir / "cv.md").write_text("MY REAL CV")

    result = CliRunner().invoke(cli, ["init", "--search-keywords", "ml, data science", "--topic-terms", "data, adat*"])
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == []

    data = json.loads((init_env.profile_dir / "config.json").read_text())
    assert data["search_keywords"] == ["ml", "data science"]
    assert data["topic_terms"] == ["data", "adat*"]
    assert data["name"] == "Existing User"
    assert data["role_targets"] == ["Old Role"]
    assert (init_env.profile_dir / "cv.md").read_text() == "MY REAL CV"


def test_init_set_takes_any_config_key(init_env, prompts):
    """`--set key=value` is the tool's `other`: JSON when it parses, a string otherwise."""
    _write_existing_profile_config(init_env)
    result = CliRunner().invoke(
        cli, ["init", "--set", "remote=hybrid", "--set", "max_age_days=14"]
    )
    assert result.exit_code == 0, result_text(result)
    data = json.loads((init_env.profile_dir / "config.json").read_text())
    assert data["remote"] == "hybrid"
    assert data["max_age_days"] == 14


def test_init_set_refuses_the_retired_feed_keys(init_env, prompts):
    _write_existing_profile_config(init_env)
    result = CliRunner().invoke(cli, ["init", "--set", 'teamtailor_companies=["storytel"]'])
    assert result.exit_code != 0
    assert "teamtailor_companies" in result_text(result)


def test_init_exclude_flags_merge_key_by_key(init_env, prompts):
    _write_existing_profile_config(init_env, exclude={"companies": ["A"], "keywords": ["intern"]})
    result = CliRunner().invoke(cli, ["init", "--exclude-companies", "B, C"])
    assert result.exit_code == 0, result_text(result)
    data = json.loads((init_env.profile_dir / "config.json").read_text())
    assert data["exclude"] == {"companies": ["B", "C"], "keywords": ["intern"]}


def test_init_with_flags_rejects_invalid_values_without_writing(init_env, prompts):
    result = CliRunner().invoke(cli, ["init", "--min-score", "1.5"])
    assert result.exit_code == 1
    assert "Error: invalid profile" in result_text(result)
    assert not (init_env.profile_dir / "config.json").exists()


def test_init_with_flags_over_an_invalid_config_drops_its_invalid_keys_and_says_so(init_env, prompts):
    _write_existing_profile_config(init_env, foo=1)
    result = CliRunner().invoke(cli, ["init", "--set", "remote=hybrid"])
    assert result.exit_code == 0, result_text(result)
    assert "foo" not in json.loads((init_env.profile_dir / "config.json").read_text())
    assert "Removed from profile/config.json, as it was not valid: foo" in result_text(result)


def test_init_set_rejects_a_value_without_equals(init_env, prompts):
    result = CliRunner().invoke(cli, ["init", "--set", "remote"])
    assert result.exit_code != 0
    assert "KEY=VALUE" in result_text(result)


# --------------------------------------------------------------------------- #
# init's wizard: CV, keywords and a first run after the details
# --------------------------------------------------------------------------- #

def test_redoing_the_review_keeps_the_sources_alone_and_starts_from_the_saved_values(init_env, prompts, wizard_calls):
    _write_existing_profile_config(init_env, name="Existing User", linkedin_discovery=True)
    before = _config(init_env)
    prompts.answers.update(steps=["review"])
    _invoke()
    assert "cv_sources" not in prompts.order and wizard_calls.drafts == []
    assert prompts.asked["discovery_pick"]["default"] == ["linkedin_discovery"]
    after = _config(init_env)
    assert after["name"] == "Existing User" and after["linkedin_discovery"] is True
    assert after["exclude"] == before["exclude"] and after["min_score"] == before["min_score"]


def test_redoing_the_sources_offers_new_titles_and_keeps_the_saved_details(init_env, prompts, wizard_calls, monkeypatch):
    _write_existing_profile_config(init_env, name="Existing User")
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(steps=["sources", "review"], **_JANE)
    _invoke()
    assert wizard_calls.drafts == [["old-cv.pdf"]]
    assert prompts.asked["titles_pick"]["choices"][2] == ("Quant: maths", "Quant")
    config = _config(init_env)
    assert config["name"] == "Existing User"
    assert (init_env.profile_dir / "cv.md").read_text() == _CV


def test_languages_help_lists_the_supported_languages(monkeypatch):
    """`init --help` names every language with a file, not a hand-written list."""
    from door import i18n
    from door.commands import profile as profile_cmd

    result = CliRunner().invoke(cli, ["init", "--help"])
    assert i18n.supported_language_names() in " ".join(result.output.split())

    monkeypatch.setattr(i18n, "supported_language_names", lambda: "English, Danish, Klingon")
    assert "English, Danish, Klingon" in profile_cmd._languages_help()


# --------------------------------------------------------------------------- #
# init's Google Drive step (#265)
# --------------------------------------------------------------------------- #
from pathlib import Path  # noqa: E402

from door.core import drive  # noqa: E402


class _Drive:
    """A fake Google Drive: connect() stores a state, one archive blob."""

    def __init__(self, monkeypatch):
        self.blob, self.version, self.connects = None, 0, 0
        monkeypatch.setattr(drive, "CLIENT_ID", "id")
        monkeypatch.setattr(drive, "CLIENT_SECRET", "secret")
        monkeypatch.setattr(drive, "connect", self.connect)
        monkeypatch.setattr(drive, "remote_meta", lambda: None if self.blob is None else {"id": "A", "version": str(self.version)})
        monkeypatch.setattr(drive, "download", lambda dest: Path(dest).write_bytes(self.blob))
        monkeypatch.setattr(drive, "upload", self.upload)
        self.fail_connect = None

    def connect(self, **kw):
        if self.fail_connect:
            raise self.fail_connect
        self.connects += 1
        drive.write_state({"refresh_token": "rt", "account": "me@x.org"})
        return {"account": "me@x.org"}

    def upload(self, src):
        self.blob = Path(src).read_bytes()
        self.version += 1
        return str(self.version)


@pytest.fixture
def fake_drive(monkeypatch, tmp_path):
    from door.core import workspace

    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(workspace, "BACKUPS_DIR", tmp_path / "backups")
    return _Drive(monkeypatch)


def test_drive_is_the_first_step_and_in_the_redo_list(init_env, prompts):
    assert next(iter(profile_cmd._STEPS)) == "drive"
    _write_existing_profile_config(init_env, name="Existing User")
    prompts.answers.update(steps=[])
    CliRunner().invoke(cli, ["init"])
    assert "drive" in [value for _label, value in prompts.asked["steps"]["choices"]]


def test_drive_step_skips_with_one_line_when_unconfigured(init_env, prompts):
    prompts.answers.update({})
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert "drive" not in prompts.order
    assert result_text(result).count("not configured in this build") == 1


def test_drive_step_declined_connects_nothing(init_env, prompts, fake_drive):
    prompts.answers.update(drive=False)
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert fake_drive.connects == 0 and fake_drive.blob is None
    assert prompts.order[0] == "drive"


def test_first_computer_ends_with_the_result_on_drive(init_env, prompts, fake_drive):
    prompts.answers.update(drive=True)
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert fake_drive.connects == 1
    assert fake_drive.blob is not None and fake_drive.version == 1
    assert "drive_pull" not in prompts.order


def test_second_computer_is_offered_the_drive_data_and_jumps_to_done(init_env, prompts, fake_drive, tmp_path):
    prompts.answers.update(drive=True)
    CliRunner().invoke(cli, ["init"])  # computer one
    shutil.rmtree(init_env.profile_dir)
    shutil.rmtree(tmp_path / "jobs", ignore_errors=True)
    drive.clear_state()
    prompts.order.clear()

    result = CliRunner().invoke(cli, ["init"])  # a fresh clone, same account
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == ["drive", "drive_pull"]
    config = json.loads((init_env.profile_dir / "config.json").read_text())
    assert config["name"] == "Jane Doe"
    assert "Done." in result_text(result)


def test_second_computer_can_decline_the_drive_data(init_env, prompts, fake_drive, tmp_path):
    prompts.answers.update(drive=True)
    CliRunner().invoke(cli, ["init"])
    shutil.rmtree(init_env.profile_dir)
    drive.clear_state()
    version = fake_drive.version
    prompts.answers.update(drive_pull=False, name="Other Person")
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert fake_drive.version == version  # the wizard did not overwrite Drive
    assert "data sync" in result_text(result)


def test_a_failed_connect_warns_and_the_wizard_continues(init_env, prompts, fake_drive):
    fake_drive.fail_connect = drive.DriveError("denied")
    prompts.answers.update(drive=True)
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert "denied" in result_text(result)
    assert (init_env.profile_dir / "config.json").exists()


def test_a_failed_push_at_the_end_only_warns(init_env, prompts, fake_drive, monkeypatch):
    def down(src):
        raise drive.DriveOffline("down")

    monkeypatch.setattr(drive, "upload", down)
    prompts.answers.update(drive=True)
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert "Done." in result_text(result)
    assert "Drive" in result_text(result)


def test_drive_can_be_the_only_step_selected(init_env, prompts, fake_drive):
    _write_existing_profile_config(init_env, name="Existing User")
    prompts.answers.update(steps=["drive"], drive=True)
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result_text(result)
    assert fake_drive.connects == 1 and "name" not in prompts.order


# --------------------------------------------------------------------------- #
# init --show / show_profile (issue #217)
# --------------------------------------------------------------------------- #

def _example_profile(init_env):
    shutil.copytree(init_env.example_dir, init_env.profile_dir)
    (init_env.profile_dir / "story_bank.md").unlink(missing_ok=True)
    config_path = init_env.profile_dir / "config.json"
    config = json.loads(config_path.read_text())
    for field, filename in (("cv_template", "cv.template.tex"), ("cv_content", "cv.md"),
                            ("cover_letter_template", "cover-letter.template.tex")):
        config[field] = str(init_env.profile_dir / filename)
    config_path.write_text(json.dumps(config))
    return init_env.profile_dir


def test_parse_cv_headline_sections_roles_and_bullets():
    parsed = profile_cmd._parse_cv((_REAL_PROFILE_EXAMPLE_DIR / "cv.md").read_text())
    assert parsed["headline"] == "Jane Doe"
    titles = [s["title"] for s in parsed["sections"]]
    assert titles[:3] == ["Profile", "Work Experience", "Education"]
    work = parsed["sections"][1]
    assert work["roles"][0].startswith("Senior Financial Controller")
    assert len(work["roles"]) == 3 and work["bullets"] == 9


def test_parse_cv_empty_and_without_sections():
    assert profile_cmd._parse_cv("") == {"headline": None, "sections": []}
    assert profile_cmd._parse_cv("# Me\n\n- a bullet\n") == {"headline": "Me", "sections": []}


def test_show_profile_core_example_profile(init_env):
    profile_dir = _example_profile(init_env)
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)
    assert result["path"] == str(profile_dir) and result["errors"] == []
    assert result["config"]["name"] == "Jane Doe"
    assert result["cv"]["is_example"] and result["cv"]["exists"] and result["cv"]["headline"] == "Jane Doe"
    assert result["cv"]["text"].startswith("# Jane Doe")
    assert result["templates"]["cv"]["is_example"] and result["templates"]["cover_letter"]["is_example"]
    assert result["story_bank"]["exists"] is False and result["story_bank"]["is_example"] is False
    assert result["enrich_sources"] == []


def test_show_profile_core_for_one_city_offers_only_that_city(init_env):
    """A conversation asks about one city: its options stay small enough to read in one answer."""
    profile_dir = _example_profile(init_env)
    every = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)["options"]["cities"]
    one = profile_cmd._show_profile_core(profile_dir, init_env.example_dir, location="copenhagen")["options"]["cities"]
    assert len(every) > 1
    assert [c["name"] for c in one] == ["Copenhagen"] and one[0] == next(c for c in every if c["name"] == "Copenhagen")


def test_show_profile_core_for_an_unknown_city_offers_none(init_env):
    profile_dir = _example_profile(init_env)
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir, location="Atlantis")
    assert result["options"]["cities"] == [] and result["options"]["worldwide_discovery"] is not None


def test_show_profile_core_edited_cv_is_not_example(init_env):
    profile_dir = _example_profile(init_env)
    cv = profile_dir / "cv.md"
    cv.write_text(cv.read_text() + "\nmore\n")
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)
    assert result["cv"]["is_example"] is False and result["cv"]["exists"]


def test_show_profile_core_invalid_config_reports_errors(init_env):
    profile_dir = _example_profile(init_env)
    (profile_dir / "config.json").write_text(json.dumps({"min_score": 7}))
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)
    assert result["config"] is None and result["errors"]
    assert result["cv"]["exists"]


def test_show_profile_core_missing_config(init_env):
    profile_dir = _example_profile(init_env)
    (profile_dir / "config.json").unlink()
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)
    assert result["config"] is None and result["errors"] and result["enrich_sources"] == []
    assert result["cv"]["exists"] and result["templates"]["cv"]["path"] == str(profile_dir / "cv.template.tex")


def test_show_profile_core_missing_files(init_env):
    profile_dir = init_env.profile_dir
    profile_dir.mkdir()
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)
    assert result["cv"] == {"path": str(profile_dir / "cv.md"), "exists": False, "is_example": False,
                            "text": None, "headline": None, "sections": []}


def test_show_profile_core_template_paths_and_sources_come_from_config(init_env):
    profile_dir = _example_profile(init_env)
    config = json.loads((profile_dir / "config.json").read_text())
    custom = profile_dir / "mine.md"
    custom.write_text("# Mine\n")
    config.update(cv_content=str(custom), enrich_sources=["https://x.example"])
    (profile_dir / "config.json").write_text(json.dumps(config))
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)
    assert result["cv"]["path"] == str(custom) and result["cv"]["headline"] == "Mine"
    assert result["enrich_sources"] == ["https://x.example"]


def test_init_show_prints_the_profile_and_writes_nothing(init_env):
    profile_dir = _example_profile(init_env)
    before = {p: p.read_bytes() for p in profile_dir.rglob("*") if p.is_file()}
    result = CliRunner().invoke(cli, ["init", "--show"])
    assert result.exit_code == 0, result_text(result)
    out = result_text(result)
    assert "Jane Doe" in out and "example" in out.lower()
    assert {p: p.read_bytes() for p in profile_dir.rglob("*") if p.is_file()} == before


def test_init_show_on_invalid_config_prints_errors_and_exits_zero(init_env):
    profile_dir = _example_profile(init_env)
    (profile_dir / "config.json").write_text(json.dumps({"min_score": 7}))
    result = CliRunner().invoke(cli, ["init", "--show"])
    assert result.exit_code == 0, result_text(result)
    assert "min_score" in result_text(result)


@pytest.mark.parametrize("extra", [["--name", "X"], ["--set", "a=1"]])
def test_init_show_cannot_be_combined_with_field_options(init_env, extra):
    result = CliRunner().invoke(cli, ["init", "--show", *extra])
    assert result.exit_code != 0
    assert "--show cannot be combined with field options" in result_text(result)


# --------------------------------------------------------------------------- #
# show_profile.options and save_cv (issue #221: the app's onboarding wizard)
# --------------------------------------------------------------------------- #

def test_show_profile_options_on_an_empty_home(init_env):
    result = profile_cmd._show_profile_core(init_env.profile_dir, init_env.example_dir)
    assert result["config"] is None
    options = result["options"]
    cities = {c["name"]: c for c in options["cities"]}
    assert "Copenhagen" in cities
    assert set(cities["Copenhagen"]) == {"name", "country", "boards", "discovery", "cv"}
    assert [d["key"] for d in cities["Copenhagen"]["discovery"]] == ["linkedin_discovery"]
    assert [d["label"] for d in options["worldwide_discovery"]] == ["LinkedIn"]
    assert result["discovery_unchosen"] == []
    assert cities["Copenhagen"]["country"] == "Denmark" and "jobindex" in cities["Copenhagen"]["boards"]
    from door import i18n
    assert options["languages"] == i18n.supported_language_names().split(", ")
    assert options["languages"][0] == "English" and "Danish" in options["languages"]
    from door.core import sites
    assert options["worldwide_boards"] == [n for n in sites.BOARDS if not sites.SITES[n].countries]
    assert options["worldwide_boards"]
    # Every board offered is named in words, as the posting pane names a site ("via The Hub").
    offered = {b for c in options["cities"] for b in c["boards"]} | set(options["worldwide_boards"])
    assert set(options["board_names"]) == offered
    assert options["board_names"]["thehub"] == "The Hub"
    assert options["board_names"]["jobindex"] == sites.source_name("jobindex")


def test_show_profile_options_are_there_with_a_config(init_env):
    profile_dir = _example_profile(init_env)
    result = profile_cmd._show_profile_core(profile_dir, init_env.example_dir)
    assert result["config"] is not None and result["options"]["cities"]


def test_show_profile_describes_every_config_key(init_env):
    # The app's profile form is built from these: every Profile key, in order, typed, with its default.
    fields = profile_cmd._show_profile_core(init_env.profile_dir, init_env.example_dir)["options"]["fields"]
    assert [f["key"] for f in fields] == list(profile_loader.Profile.model_fields)
    by = {f["key"]: f for f in fields}
    assert by["name"] == {"key": "name", "type": "string", "required": True, "nullable": False}
    assert by["remote"] == {"key": "remote", "type": "choice", "required": True, "nullable": False, "choices": ["yes", "no", "hybrid"]}
    assert by["role_targets"]["type"] == "list" and by["role_targets"]["required"] is True
    assert by["cv_template"]["type"] == "path"
    assert by["min_score"] == {"key": "min_score", "type": "number", "required": False, "nullable": False, "default": 0.65}
    assert by["max_age_days"] == {"key": "max_age_days", "type": "integer", "required": False, "nullable": True, "default": 30, "min": 1}
    assert by["retire_after_days"] == {"key": "retire_after_days", "type": "integer", "required": False, "nullable": False, "default": 90, "min": 0}
    assert by["dedup_similarity_threshold"] == {
        "key": "dedup_similarity_threshold", "type": "number", "required": False, "nullable": False, "default": 1.0, "min": 0.0, "max": 1.0,
    }
    assert by["scrape_workers"] == {"key": "scrape_workers", "type": "integer", "required": False, "nullable": True, "default": None, "min": 1}
    assert by["claude_config_dir"] == {"key": "claude_config_dir", "type": "string", "required": False, "nullable": True, "default": None}
    assert by["linkedin_discovery"] == {"key": "linkedin_discovery", "type": "boolean", "required": False, "nullable": False, "default": False}
    assert by["exclude"] == {"key": "exclude", "type": "exclude", "required": False, "nullable": False, "default": {"companies": [], "keywords": []}}
    json.dumps(fields)


def test_the_app_profile_form_places_every_config_key():
    # Each config key is placed on purpose (#404): in a section of the app's Profile screen, or in the
    # "config" section, left to profile/config.json (tuning and file paths). A new key must be one or the other.
    form = json.loads((REPO_ROOT / "app" / "src" / "renderer" / "screens" / "profile-form" / "fields.json").read_text())
    assert [f["key"] for f in form["fields"]] == list(profile_loader.Profile.model_fields)
    sections = {s["id"] for s in form["sections"]}
    assert "config" in sections
    assert all(f["section"] in sections for f in form["fields"])
    shown = {f["key"] for f in form["fields"] if f["section"] != "config"}
    assert {"name", "email", "location", "role_targets", "remote", "min_score", "languages"} <= shown


def test_init_errors_name_the_key_first(init_env):
    # The app puts each error under its field by the key after the file name.
    with pytest.raises(profile_loader.ConfigError) as exc:
        profile_cmd._init_core(
            profile_cmd._profile_fields(remote="sometimes", other={"max_age_days": 0, "exclude": {"companies": [], "x": 1}}),
            profile_dir=init_env.profile_dir, example_dir=init_env.example_dir,
        )
    lines = str(exc.value).splitlines()
    import re

    keys = sorted(re.match(r"^.+?: ([\w.]+) — .+$", line).group(1) for line in lines)
    assert keys == ["exclude.x", "max_age_days", "remote"]


def test_save_cv_core_writes_cv_md_and_drops_the_draft(init_env):
    init_env.profile_dir.mkdir()
    (init_env.profile_dir / "cv.md").write_text("OLD")
    (init_env.profile_dir / "cv.draft.md").write_text("draft")
    (init_env.profile_dir / "config.json").write_text('{"keep": 1}')
    result = profile_cmd._save_cv_core("# Me\n\nNEW\n")
    assert (init_env.profile_dir / "cv.md").read_text() == "# Me\n\nNEW\n"
    assert result == {"cv_path": str(init_env.profile_dir / "cv.md"), "backup": str(init_env.profile_dir / "cv.md.bak")}
    assert (init_env.profile_dir / "cv.md.bak").read_text() == "OLD"
    assert not (init_env.profile_dir / "cv.draft.md").exists()
    assert (init_env.profile_dir / "config.json").read_text() == '{"keep": 1}'


def test_save_cv_core_first_cv_has_no_backup(init_env):
    result = profile_cmd._save_cv_core("# Me\n")
    assert result == {"cv_path": str(init_env.profile_dir / "cv.md"), "backup": None}
    assert not (init_env.profile_dir / "cv.md.bak").exists()


def test_save_cv_core_keeps_a_cv_that_is_not_text_byte_for_byte(init_env):
    init_env.profile_dir.mkdir()
    old = bytes([0xFF, 0xFE, 0x00, 0x41, 0xC3, 0x28])
    (init_env.profile_dir / "cv.md").write_bytes(old)
    profile_cmd._save_cv_core("# Me\n")
    assert (init_env.profile_dir / "cv.md.bak").read_bytes() == old


def test_save_cv_core_creates_the_profile_folder(init_env):
    result = profile_cmd._save_cv_core("# Me\n")
    assert (init_env.profile_dir / "cv.md").read_text() == "# Me\n"
    assert "error" not in result


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_save_cv_core_refuses_empty_text_and_writes_nothing(init_env, text):
    result = profile_cmd._save_cv_core(text)
    assert "error" in result
    assert not init_env.profile_dir.exists()


def _disclaimed(init_env, fields):
    return [d["key"] for d in profile_cmd._init_core(fields, init_env.profile_dir, init_env.example_dir)["disclaimers"]]


def test_turning_a_source_on_returns_its_disclaimer(init_env):
    from door.core import discovery_sources

    result = profile_cmd._init_core({"linkedin_discovery": True}, init_env.profile_dir, init_env.example_dir)
    assert result["disclaimers"] == [{"key": "linkedin_discovery", "text": discovery_sources.info("linkedin")["disclaimer"]}]


def test_a_disclaimer_comes_only_when_a_source_goes_from_not_on_to_on(init_env):
    _write_existing_profile_config(init_env, linkedin_discovery=True, profession_discovery=False)
    assert _disclaimed(init_env, {"linkedin_discovery": True}) == []  # already on
    assert _disclaimed(init_env, {"linkedin_discovery": False}) == []  # turned off
    assert _disclaimed(init_env, {"profession_discovery": False}) == []  # stays off
    assert _disclaimed(init_env, {"profession_discovery": True, "linkedin_discovery": False}) == ["profession_discovery"]
    assert _disclaimed(init_env, {"linkedin_discovery": True, "profession_discovery": True}) == ["linkedin_discovery"]


def test_init_set_prints_the_disclaimer_once(init_env):
    from door.core import discovery_sources

    first = CliRunner().invoke(cli, ["init", "--set", "linkedin_discovery=true"])
    assert discovery_sources.info("linkedin")["disclaimer"] in result_text(first)
    again = CliRunner().invoke(cli, ["init", "--set", "linkedin_discovery=true"])
    assert "LEGAL_DISCLAIMER.md" not in result_text(again)


def test_the_wizards_discovery_question_is_the_generated_disclaimer(init_env, prompts, monkeypatch):
    from door.core import discovery_sources

    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    message = prompts.asked["discovery_pick"]["message"]
    for source in discovery_sources.for_location("Copenhagen"):
        assert source["disclaimer"] in message


def test_show_profile_names_the_discovery_sources_not_chosen_yet(init_env):
    _write_existing_profile_config(init_env, location="Budapest", linkedin_discovery=True)
    result = profile_cmd._show_profile_core(init_env.profile_dir, init_env.example_dir)
    assert [d["key"] for d in result["discovery_unchosen"]] == ["profession_discovery"]
    assert {"verdict", "terms_url", "terms_summary", "disclaimer"} <= set(result["discovery_unchosen"][0])


# --- the CV photo (#605) ---------------------------------------------------


def _picture(path, size=(900, 1200)):
    from PIL import Image

    Image.new("RGB", size, "tan").save(path, "JPEG")
    return path


def test_save_photo_core_keeps_a_cleaned_copy_and_names_it_in_the_config(init_env, tmp_path):
    _write_existing_profile_config(init_env)
    source = _picture(tmp_path / "me.jpg")
    result = profile_cmd._save_photo_core(str(source))
    kept = init_env.profile_dir / "photo.jpg"
    assert result["photo_path"] == str(kept) and kept.is_file()
    assert json.loads((init_env.profile_dir / "config.json").read_text())["photo"] == str(kept)
    assert source.exists()  # the user's own file is untouched


def test_save_photo_core_refuses_a_file_that_is_not_a_picture_and_changes_nothing(init_env, tmp_path):
    _write_existing_profile_config(init_env)
    (tmp_path / "me.jpg").write_bytes(b"%PDF-1.4")
    result = profile_cmd._save_photo_core(str(tmp_path / "me.jpg"))
    assert "JPEG or PNG" in result["error"]
    assert not (init_env.profile_dir / "photo.jpg").exists()
    assert "photo" not in json.loads((init_env.profile_dir / "config.json").read_text())


def test_save_photo_core_before_any_profile_exists_copies_the_example_first(init_env, tmp_path):
    result = profile_cmd._save_photo_core(str(_picture(tmp_path / "me.jpg")))
    assert "error" not in result
    assert json.loads((init_env.profile_dir / "config.json").read_text())["photo"] == str(init_env.profile_dir / "photo.jpg")


def test_remove_photo_core_deletes_the_copy_and_the_key(init_env, tmp_path):
    _write_existing_profile_config(init_env)
    profile_cmd._save_photo_core(str(_picture(tmp_path / "me.jpg")))
    result = profile_cmd._remove_photo_core()
    assert result == {"removed": True}
    assert not (init_env.profile_dir / "photo.jpg").exists()
    assert json.loads((init_env.profile_dir / "config.json").read_text()).get("photo") is None
    assert profile_cmd._remove_photo_core() == {"removed": False}


def test_show_profile_says_whether_there_is_a_photo(init_env, tmp_path):
    _write_existing_profile_config(init_env)
    assert profile_cmd._show_profile_core(init_env.profile_dir, init_env.example_dir)["photo"] == {"exists": False}
    profile_cmd._save_photo_core(str(_picture(tmp_path / "me.jpg")))
    shown = profile_cmd._show_profile_core(init_env.profile_dir, init_env.example_dir)["photo"]
    assert shown["exists"] is True and shown["path"] == str(init_env.profile_dir / "photo.jpg")


def test_profile_options_give_each_city_its_countrys_cv_conventions():
    cities = {c["name"]: c for c in profile_cmd._profile_options()["cities"]}
    assert cities["Copenhagen"]["cv"]["photo"] == "optional"
    assert cities["London"]["cv"] == {"photo": "no", "date_of_birth": False, "max_pages": 2, "date_format": "DD/MM/YYYY"}


def test_init_asks_for_a_photo_once_only_where_the_countrys_cvs_may_carry_one(init_env, prompts, monkeypatch, wizard_calls):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    wizard_calls.basics = _basics(location="London")
    CliRunner().invoke(cli, ["init"])
    assert "photo" not in prompts.order


def test_init_skips_the_photo_on_enter_and_saves_none(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    CliRunner().invoke(cli, ["init"])
    assert prompts.order.count("photo") == 1
    assert not _config(init_env).get("photo") and not (init_env.profile_dir / "photo.jpg").exists()


def test_init_keeps_the_photo_it_is_given_after_the_profile_is_saved(init_env, prompts, monkeypatch, tmp_path):
    _stop_at_first_run(monkeypatch)
    _picture(tmp_path / "me.jpg")
    prompts.answers.update(_JANE, photo=str(tmp_path / "me.jpg"))
    CliRunner().invoke(cli, ["init"])
    assert (init_env.profile_dir / "photo.jpg").is_file()
    assert _config(init_env)["photo"] == str(init_env.profile_dir / "photo.jpg")


def test_init_checks_the_photo_where_it_is_asked(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4")
    assert "JPEG or PNG" in profile_cmd._photo_problem(str(tmp_path / "doc.pdf"))
    assert profile_cmd._photo_problem("") is None
    assert "not found" in profile_cmd._photo_problem(str(tmp_path / "nope.jpg"))


# --------------------------------------------------------------------------- #
# preferences (#50)
# --------------------------------------------------------------------------- #

_PREFERENCES = "medical or green energy; avoid banking and gambling"


def test_the_preferences_field_is_a_plain_optional_string(init_env):
    fields = profile_cmd._show_profile_core(init_env.profile_dir, init_env.example_dir)["options"]["fields"]
    assert {f["key"]: f for f in fields}["preferences"] == {
        "key": "preferences", "type": "string", "required": False, "nullable": False, "default": "",
    }


def test_init_set_writes_the_preferences_text_as_written(init_env):
    _write_existing_profile_config(init_env, name="Existing User", role_targets=["Old Role"])
    (init_env.profile_dir / "cv.md").write_text("MY REAL CV")
    _invoke("--set", f"preferences={_PREFERENCES}")
    assert _config(init_env)["preferences"] == _PREFERENCES


def test_init_profile_sets_and_clears_the_preferences(init_env):
    _write_existing_profile_config(init_env, name="Existing User", role_targets=["Old Role"])
    (init_env.profile_dir / "cv.md").write_text("MY REAL CV")
    profile_cmd._init_core(profile_cmd._profile_fields(other={"preferences": _PREFERENCES}), init_env.profile_dir, init_env.example_dir)
    assert _config(init_env)["preferences"] == _PREFERENCES
    profile_cmd._init_core(profile_cmd._profile_fields(other={"preferences": ""}), init_env.profile_dir, init_env.example_dir)
    assert _config(init_env)["preferences"] == ""


def test_the_wizard_asks_for_preferences_once_after_the_search_terms_and_saves_them(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, preferences=_PREFERENCES)
    text = result_text(CliRunner().invoke(cli, ["init"]))
    assert prompts.order.count("preferences") == 1
    assert prompts.order.index("preferences") < prompts.order.index("review")
    assert "rule out" in prompts.asked["preferences"]["message"] and "optional" in prompts.asked["preferences"]["message"]
    assert _config(init_env)["preferences"] == _PREFERENCES
    assert "What matters to you" in text and _PREFERENCES in text


def test_skipping_the_preferences_question_saves_none(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE)
    text = result_text(CliRunner().invoke(cli, ["init"]))
    assert _config(init_env).get("preferences", "") == ""
    assert "What matters to you" in text and "none" in text.split("What matters to you", 1)[1].splitlines()[0]


def test_the_review_can_change_the_preferences(init_env, prompts, monkeypatch):
    _stop_at_first_run(monkeypatch)
    prompts.answers.update(_JANE, review=iter(["preferences", "save"]), preferences=iter(["", "robotics"]))
    CliRunner().invoke(cli, ["init"])
    assert _config(init_env)["preferences"] == "robotics"


def test_the_first_look_scores_with_the_preferences(init_env, prompts, wizard_calls, monkeypatch):
    _stop_at_first_run(monkeypatch)
    seen = {}
    from door.commands import preview as preview_cmd

    def look(config, cv, **k):
        seen.update(config)
        return {"board": "jobindex", "matches": []}

    monkeypatch.setattr(preview_cmd, "_preview_core", look)
    prompts.answers.update(_JANE, preferences=_PREFERENCES)
    CliRunner().invoke(cli, ["init"])
    assert seen["preferences"] == _PREFERENCES
