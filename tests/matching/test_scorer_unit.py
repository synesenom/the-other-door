"""Unit tests for src/door/matching/scorer.py (issue #128).

Pure/offline: no subprocess, no network. Exercises system-prompt building
(rubric extraction from .claude/agents/matcher.md + profile), user-message
building (description_condensed with a 6000-char cap), the `claude -p`
argv builder, the `--output-format json` envelope parser, and apply_result's
prefilter/prescreen hard-zero guard.
"""

import json

import pytest

from door.matching import scorer


# --------------------------------------------------------------------------- #
# Synthetic rubric markdown mirroring .claude/agents/matcher.md's structure
# --------------------------------------------------------------------------- #

_SAMPLE_RUBRIC_MD = """---
name: matcher
tools:
  - WebSearch
---

You are the matcher agent.

## Scoring rubric (0–1)

| Criterion | Weight |
|-----------|--------|
| Title match | 0.30 |

## Compensation research

Only perform compensation research if a salary is stated. +0.10 above market, -0.10 below market.

## Legitimacy / ghost-job check

3+ signals co-occurring is a hard zero.

## Language requirements

A required language the candidate doesn't work in is a strong negative, not a hard zero.

## Output

For each posting JSON, write back score/score_reason/matching_skills/missing_skills.

## Behaviour

Never invent URLs.
"""


# --------------------------------------------------------------------------- #
# build_system_prompt
# --------------------------------------------------------------------------- #


def _profile_cfg():
    return {
        "role_targets": ["Lead Data Scientist"],
        "location": "Copenhagen",
        "remote": "hybrid",
        "languages": ["English", "Danish"],
        "min_score": 0.65,
        "exclude": {"companies": ["Bad Co"], "keywords": ["unpaid"]},
    }


def test_build_system_prompt_is_byte_stable_across_calls():
    cv_md = "# CV\n\n## Skills\n\nPython, SQL\n"
    a = scorer.build_system_prompt(_profile_cfg(), cv_md, _SAMPLE_RUBRIC_MD)
    b = scorer.build_system_prompt(_profile_cfg(), cv_md, _SAMPLE_RUBRIC_MD)
    assert a == b


def test_build_system_prompt_includes_only_rubric_sections():
    prompt = scorer.build_system_prompt({}, "", _SAMPLE_RUBRIC_MD)
    assert "Scoring rubric" in prompt
    assert "Language requirements" in prompt
    # The WebSearch-based sections are the agent's alone: `claude -p` runs
    # here with no tools, so telling the model to search would only waste
    # tokens and invite invented "no web presence" penalties.
    assert "Compensation research" not in prompt
    assert "Legitimacy / ghost-job check" not in prompt
    assert "WebSearch" not in prompt
    # Non-rubric sections (Output/Behaviour) must not be duplicated in full —
    # the schema (not this section) governs output shape.
    assert "## Output" not in prompt
    assert "## Behaviour" not in prompt


def test_build_system_prompt_lists_the_language_requirement_phrases():
    """The phrase lists live in src/door/i18n/lang/*.toml, so a new language
    needs no prompt edit."""
    prompt = scorer.build_system_prompt({}, "", _SAMPLE_RUBRIC_MD)
    assert "## Language requirement phrases" in prompt
    assert '"dansk er et krav"' in prompt
    assert '"dansk er en fordel"' in prompt


def test_build_system_prompt_lists_the_false_friends():
    """An exclude keyword that is an ordinary word in the ad's language is
    not applied; the words come from src/door/i18n/lang/*.toml."""
    prompt = scorer.build_system_prompt({}, "", _SAMPLE_RUBRIC_MD)
    assert '- Danish, false friends: "intern", "chef"' in prompt


def test_the_real_rubric_sends_the_language_rule_to_the_scorer():
    sections = scorer._extract_rubric_sections(scorer.load_rubric_md())
    assert "## Scoring rubric" in sections
    assert "## Language requirements" in sections


def test_the_real_prompt_applies_exclude_keywords_to_the_title_only():
    """Like the pre-filter: a lead role whose ad mentions mentoring juniors is
    not hard-zeroed for an exclude keyword "junior" (golden set, issue #153)."""
    prompt = scorer.build_system_prompt({}, "", scorer.load_rubric_md())
    assert "description contains any" not in prompt
    assert "title contains any exclude.keywords" in prompt
    assert "title contains any `exclude.keywords`" in prompt


def test_build_system_prompt_includes_profile_fields():
    prompt = scorer.build_system_prompt(_profile_cfg(), "", _SAMPLE_RUBRIC_MD)
    assert "Lead Data Scientist" in prompt
    assert "Copenhagen" in prompt
    assert "hybrid" in prompt
    assert "Bad Co" in prompt


def test_build_system_prompt_includes_cv_content():
    cv_md = "# Jane Doe CV\n\nExpert in distributed systems."
    prompt = scorer.build_system_prompt({}, cv_md, _SAMPLE_RUBRIC_MD)
    assert "Expert in distributed systems." in prompt


# --------------------------------------------------------------------------- #
# build_user_message
# --------------------------------------------------------------------------- #


def test_build_user_message_uses_description_condensed():
    posting = {
        "title": "Data Scientist",
        "company": "Acme",
        "location": "Copenhagen",
        "posted_at": "2026-06-01",
        "description_condensed": "condensed body",
        "description": "the full original body should not appear",
    }
    msg = scorer.build_user_message(posting)
    assert "condensed body" in msg
    assert "full original body" not in msg
    assert "Data Scientist" in msg
    assert "Acme" in msg


def test_build_user_message_falls_back_to_description():
    posting = {
        "title": "Data Scientist",
        "company": "Acme",
        "location": "Copenhagen",
        "description": "only the full description here",
    }
    msg = scorer.build_user_message(posting)
    assert "only the full description here" in msg


def test_build_user_message_leaves_the_ad_language_out():
    """Ads in languages outside the profile never reach the matcher, so the
    language an ad is written in is no scoring signal."""
    posting = {"title": "Dataforsker", "company": "Acme", "location": "København", "language": "da",
               "description": "d"}
    assert "language" not in scorer.build_user_message(posting).lower()


def test_build_user_message_caps_at_6000_chars():
    posting = {
        "title": "t",
        "company": "c",
        "location": "l",
        "description_condensed": "x" * 7000,
    }
    msg = scorer.build_user_message(posting)
    assert msg.count("x") == 6000


# --------------------------------------------------------------------------- #
# build_claude_argv
# --------------------------------------------------------------------------- #


def test_build_claude_argv_contains_required_flags():
    argv = scorer.build_claude_argv("sys prompt", "haiku", scorer.SCORE_SCHEMA)
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "--tools" in argv
    tools_idx = argv.index("--tools")
    assert argv[tools_idx + 1] == ""
    assert "--json-schema" in argv
    assert "--output-format" in argv
    out_idx = argv.index("--output-format")
    assert argv[out_idx + 1] == "stream-json"
    assert "--verbose" in argv
    assert "--no-session-persistence" in argv
    assert "haiku" in argv


def test_build_claude_argv_includes_fallback_model_when_given():
    argv = scorer.build_claude_argv(
        "sys", "haiku", scorer.SCORE_SCHEMA, fallback_model="sonnet"
    )
    assert "--fallback-model" in argv
    assert "sonnet" in argv


def test_build_claude_argv_omits_fallback_model_by_default():
    argv = scorer.build_claude_argv("sys", "haiku", scorer.SCORE_SCHEMA)
    assert "--fallback-model" not in argv


# --------------------------------------------------------------------------- #
# parse_claude_output
# --------------------------------------------------------------------------- #


def _envelope(result_obj, *, is_error=False):
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": is_error,
            "result": json.dumps(result_obj) if not is_error else result_obj,
            "session_id": "child-session-abc",
        }
    )


def _valid_result():
    return {
        "score": 0.72,
        "score_reason": "Good title/skill match.",
        "matching_skills": ["Python"],
        "missing_skills": ["Kubernetes"],
        "language_requirement": "none",
        "flags": [],
    }


def test_parse_claude_output_accepts_realistic_envelope():
    parsed = scorer.parse_claude_output(_envelope(_valid_result()))
    assert parsed["score"] == 0.72
    assert parsed["matching_skills"] == ["Python"]
    assert parsed["language_requirement"] == "none"


def test_parse_claude_output_rejects_non_json_stdout():
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_claude_output("not json at all")


def test_parse_claude_output_rejects_missing_required_field():
    incomplete = {"score": 0.5, "score_reason": "ok"}
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_claude_output(_envelope(incomplete))


def test_parse_claude_output_rejects_is_error_envelope():
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_claude_output(_envelope("boom", is_error=True))


def test_parse_claude_output_rejects_out_of_range_score():
    bad = _valid_result()
    bad["score"] = 1.5
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_claude_output(_envelope(bad))


def test_the_real_rubric_ties_language_requirements_to_the_profile_languages():
    sections = scorer._extract_rubric_sections(scorer.load_rubric_md())
    assert "`implicit`" not in sections
    assert "C1" not in sections
    assert "not in `languages`" in sections


def test_parse_claude_output_rejects_implicit_language_requirement():
    bad = _valid_result()
    bad["language_requirement"] = "implicit"
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_claude_output(_envelope(bad))


def test_parse_claude_output_never_returns_partial_score_on_error():
    """On any parse failure, no dict is returned at all (exception, not a
    partially-populated result) — callers can never mistake a bad parse for
    a real (if incomplete) score."""
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_claude_output("{}")


# --------------------------------------------------------------------------- #
# apply_result
# --------------------------------------------------------------------------- #


def test_apply_result_writes_four_fields_plus_scored_meta():
    posting = {"id": "x", "score": None}
    result = {
        "score": 0.8,
        "score_reason": "good",
        "matching_skills": ["a"],
        "missing_skills": [],
        "language_requirement": "required",
        "scored_by": "haiku",
        "scored_at": "2026-09-23T00:00:00+00:00",
    }
    updated = scorer.apply_result(posting, result)
    assert updated["language_requirement"] == "required"
    assert updated["score"] == 0.8
    assert updated["score_reason"] == "good"
    assert updated["matching_skills"] == ["a"]
    assert updated["missing_skills"] == []
    assert updated["scored_by"] == "haiku"
    assert updated["scored_at"] == "2026-09-23T00:00:00+00:00"
    # original posting dict is untouched (apply_result returns a new dict)
    assert posting["score"] is None


def test_apply_result_does_not_overwrite_prefilter_hard_zero():
    posting = {"id": "x", "score": 0.0, "score_reason": "prefilter: excluded company"}
    result = {
        "score": 0.9,
        "score_reason": "great match",
        "matching_skills": [],
        "missing_skills": [],
    }
    updated = scorer.apply_result(posting, result)
    assert updated["score"] == 0.0
    assert updated["score_reason"] == "prefilter: excluded company"


def test_apply_result_does_not_overwrite_prescreen_hard_zero():
    posting = {"id": "x", "score": 0.0, "score_reason": "prescreen: 0.10 below cutoff"}
    result = {
        "score": 0.9,
        "score_reason": "great match",
        "matching_skills": [],
        "missing_skills": [],
    }
    updated = scorer.apply_result(posting, result)
    assert updated["score"] == 0.0
    assert updated["score_reason"] == "prescreen: 0.10 below cutoff"


def test_apply_result_overwrites_normal_existing_score():
    posting = {"id": "x", "score": 0.3, "score_reason": "old reason"}
    result = {
        "score": 0.9,
        "score_reason": "new reason",
        "matching_skills": ["Python"],
        "missing_skills": [],
    }
    updated = scorer.apply_result(posting, result)
    assert updated["score"] == 0.9
    assert updated["score_reason"] == "new reason"


def test_the_prompt_flags_hungarian_requirements_in_english_and_hungarian():
    prompt = scorer.build_system_prompt({}, "", _SAMPLE_RUBRIC_MD)
    lines = {ln.split(":")[0]: ln for ln in prompt.splitlines() if ln.startswith("- Hungarian")}
    required, advantage = lines["- Hungarian, required"], lines["- Hungarian, advantage"]
    for phrase in ("Hungarian required", "fluent in Hungarian", "must speak Hungarian",
                   "magyar nyelvtudás elvárás", "folyékony magyar"):
        assert f'"{phrase}"' in required
    for phrase in ("Hungarian is a plus", "Hungarian is an advantage", "magyar nyelvtudás előny"):
        assert f'"{phrase}"' in advantage


def test_an_english_ad_requiring_hungarian_is_detected_as_requiring_it():
    from door import i18n

    pack = i18n.requirement_phrases()["Hungarian"]
    rx_required = i18n.compile_words(pack.required)
    rx_advantage = i18n.compile_words(pack.advantage)
    assert rx_required.search("Candidates must have fluent Hungarian required for client calls.")
    assert rx_required.search("Fluent in Hungarian and English.")
    assert not rx_required.search("Hungarian is a plus.")
    assert rx_advantage.search("Knowledge of Hungarian is a plus for this role.")
    assert "hungarian" in [n.lower() for n in i18n.language_names()]


def test_build_argv_uses_the_resolved_claude_path(monkeypatch):
    from door.core import installers
    from door.matching import scorer

    monkeypatch.setattr(installers, "find_claude", lambda *a, **k: "/x/claude")
    assert scorer.build_claude_argv("sys", "haiku", {})[0] == "/x/claude"


# --------------------------------------------------------------------------- #
# work_permit (#326)
# --------------------------------------------------------------------------- #

_WP = ["no_sponsorship", "permit_required", "sponsorship_offered", "not_mentioned"]


def _chunk_envelope(item):
    return _envelope({"results": [{"job_id": "a", **item}]})


def test_work_permit_is_in_the_schemas():
    assert scorer.SCORE_SCHEMA["properties"]["work_permit"]["enum"] == _WP
    assert "work_permit" in scorer.SCORE_SCHEMA["required"]
    items = scorer.CHUNK_SCORE_SCHEMA["properties"]["results"]["items"]
    assert items["properties"]["work_permit"]["enum"] == _WP


def test_reply_without_work_permit_accepted():
    assert "work_permit" not in _valid_result()
    scorer.parse_claude_output(_envelope(_valid_result()))
    scorer.parse_chunk_output(_chunk_envelope(_valid_result()))


@pytest.mark.parametrize("value", _WP)
def test_each_work_permit_value_is_accepted(value):
    scorer.parse_claude_output(_envelope({**_valid_result(), "work_permit": value}))
    scorer.parse_chunk_output(_chunk_envelope({**_valid_result(), "work_permit": value}))


@pytest.mark.parametrize("value", ["maybe", 5])
def test_a_bad_work_permit_value_is_rejected(value):
    bad = {**_valid_result(), "work_permit": value}
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_claude_output(_envelope(bad))
    with pytest.raises(scorer.ScoreParseError):
        scorer.parse_chunk_output(_chunk_envelope(bad))


def _wp_result(value, score=0.8):
    return {"score": score, "score_reason": "good fit", "work_permit": value,
            "scored_by": "haiku", "scored_at": "t"}


def test_apply_result_stores_work_permit_only_when_present():
    assert scorer.apply_result({"id": "x"}, _wp_result("not_mentioned"))["work_permit"] == "not_mentioned"
    assert "work_permit" not in scorer.apply_result({"id": "x"}, {"score": 0.5, "score_reason": "r"})


@pytest.mark.parametrize("value,why", [("no_sponsorship", "no visa sponsorship offered"),
                                       ("permit_required", "work permit required")])
def test_needs_work_permit_zeroes_a_blocking_ad(value, why):
    posting = {"id": "x"}
    out = scorer.apply_result(posting, _wp_result(value), needs_work_permit=True)
    assert out["score"] == 0.0
    assert out["score_reason"].startswith("work permit: ")
    assert why in out["score_reason"]
    assert "good fit" in out["score_reason"]
    assert out["work_permit"] == value
    assert posting == {"id": "x"}


@pytest.mark.parametrize("value", ["no_sponsorship", "permit_required"])
def test_without_the_flag_the_score_is_untouched(value):
    assert scorer.apply_result({"id": "x"}, _wp_result(value))["score"] == 0.8
    assert scorer.apply_result({"id": "x"}, _wp_result(value), needs_work_permit=False)["score"] == 0.8


@pytest.mark.parametrize("value", ["sponsorship_offered", "not_mentioned", None])
def test_flag_leaves_other_values_untouched(value):
    result = _wp_result(value)
    if value is None:
        del result["work_permit"]
    out = scorer.apply_result({"id": "x"}, result, needs_work_permit=True)
    assert out["score"] == 0.8
    assert out["score_reason"] == "good fit"


def test_flag_does_not_override_a_prefilter_zero():
    posting = {"id": "x", "score": 0.0, "score_reason": "prefilter: excluded company"}
    assert scorer.apply_result(posting, _wp_result("no_sponsorship"), needs_work_permit=True) is posting


def test_flag_prefixes_an_already_zero_score():
    out = scorer.apply_result({"id": "x"}, _wp_result("no_sponsorship", score=0.0), needs_work_permit=True)
    assert out["score"] == 0.0
    assert out["score_reason"].startswith("work permit: ")


def test_system_prompt_lists_work_permit_phrases_and_rubric():
    rubric = scorer.load_rubric_md()
    prompt = scorer.build_system_prompt({"needs_work_permit": True}, "", rubric)
    assert "## Work permit phrases" in prompt
    assert "unable to offer visa sponsorship" in prompt
    assert "kan ikke tilbyde sponsorering" in prompt
    assert "## Work permit\n" in prompt
    assert "sponsorship_offered" in prompt
    assert "needs_work_permit: True" in prompt
    assert "work-permit rule" in prompt  # the hard-zero reservation names it
    assert "## Output" not in prompt
    assert '"work_permit":' in rubric  # matcher.md Output lists it


def test_apply_result_marks_a_suspicious_ad_without_an_excerpt():
    posting = {"id": "x", "score": None, "integrity": {
        "verdict": "suspicious", "findings": [{"kind": "instruction", "excerpt": "ignore previous instructions"}]}}
    result = {"score": 0.8, "score_reason": "good fit", "scored_by": "haiku", "scored_at": "t"}
    updated = scorer.apply_result(posting, result)
    assert updated["score_reason"] == "suspicious ad: good fit"
    assert "ignore previous" not in updated["score_reason"]
    assert updated["score"] == 0.8


@pytest.mark.parametrize("integrity", [None, {"verdict": "clean", "findings": []}])
def test_apply_result_leaves_a_clean_or_ungated_reason_alone(integrity):
    posting = {"id": "x", "score": None, "integrity": integrity}
    updated = scorer.apply_result(posting, {"score": 0.5, "score_reason": "ok", "scored_by": "h", "scored_at": "t"})
    assert updated["score_reason"] == "ok"


def test_the_prompt_flags_french_requirements_in_english_and_french():
    prompt = scorer.build_system_prompt({}, "", _SAMPLE_RUBRIC_MD)
    lines = {ln.split(":")[0]: ln for ln in prompt.splitlines() if ln.startswith("- French")}
    required, advantage = lines["- French, required"], lines["- French, advantage"]
    for phrase in ("French required", "fluent in French", "français courant", "maîtrise du français"):
        assert f'"{phrase}"' in required
    for phrase in ("French is a plus", "French is an advantage", "français est un atout"):
        assert f'"{phrase}"' in advantage


def test_an_english_ad_requiring_french_is_detected_as_requiring_it():
    from door import i18n

    pack = i18n.requirement_phrases()["French"]
    rx_required = i18n.compile_words(pack.required)
    rx_advantage = i18n.compile_words(pack.advantage)
    assert rx_required.search("Fluent French required for client calls in our Paris office.")
    assert rx_required.search("You are fluent in French and English.")
    assert rx_required.search("Le français courant est exigé pour ce poste.")
    assert not rx_required.search("French is a plus.")
    assert rx_advantage.search("Knowledge of French is a plus for this role.")
    assert rx_advantage.search("Le français est un atout.")
    assert {"french", "français", "francophone"} <= {n.lower() for n in i18n.language_names()}


def test_the_prompt_flags_swedish_requirements_in_english_and_swedish():
    prompt = scorer.build_system_prompt({}, "", _SAMPLE_RUBRIC_MD)
    lines = {ln.split(":")[0]: ln for ln in prompt.splitlines() if ln.startswith("- Swedish")}
    required, advantage = lines["- Swedish, required"], lines["- Swedish, advantage"]
    for phrase in ("Swedish required", "fluent in Swedish", "must speak Swedish",
                   "flytande svenska", "svenska i tal och skrift"):
        assert f'"{phrase}"' in required
    for phrase in ("Swedish is a plus", "Swedish is an advantage", "svenska är meriterande"):
        assert f'"{phrase}"' in advantage


def test_an_english_ad_requiring_swedish_is_detected_as_requiring_it():
    from door import i18n

    pack = i18n.requirement_phrases()["Swedish"]
    rx_required = i18n.compile_words(pack.required)
    rx_advantage = i18n.compile_words(pack.advantage)
    assert rx_required.search("Fluent Swedish required for daily client contact.")
    assert rx_required.search("You are fluent in Swedish and English.")
    assert rx_required.search("Swedish is a must for this role.")
    assert not rx_required.search("Swedish is a plus.")
    assert rx_advantage.search("Knowledge of Swedish is a plus for this role.")
    assert rx_advantage.search("Swedish is an advantage.")
    assert rx_required.search("Svenska i tal och skrift krävs.")
    assert rx_advantage.search("Kunskaper i svenska är meriterande.")
    assert "swedish" in [n.lower() for n in i18n.language_names()]
