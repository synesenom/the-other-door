"""The profession suite (#427, epic #426): six Danish profiles through the title gate, the pre-filter and the prescreen.

Data in `tests/professions.py`. Cases that fail today because of an open sub-issue of #426 are `xfail(strict=True)`
with its number; they turn green, and the mark must go, when the fix lands.
"""

import json
import re
from pathlib import Path

import pytest

from door.matching import prefilter, prescreen, title_fit
from professions import PROFESSIONS

OPEN_SUBISSUES = {438}

# (profession, title) -> reason; filled from running every case.
XFAIL_TOPIC: dict[tuple[str, str], str] = {}
XFAIL_KEYWORDS_ONLY: dict[tuple[str, str], str] = {}
# Titles only explicit `topic_terms` can carry: an institute name is never a search keyword, a rank is no topic word,
# and an employer-branded title names the store, not the job, so the keywords-only fallback has nothing to match them
# on. Not a defect; left out of that test.
TOPIC_TERMS_ONLY = {("researcher", "Tenure-track Assistant Professor, Niels Bohr Institute"),
                    ("shop_sales", "Deltidsmedarbejder til vores butik i Lyngby")}
XFAIL_OFF_TOPIC: dict[tuple[str, str], str] = {}
XFAIL_OFF_KEYWORDS_ONLY: dict[tuple[str, str], str] = {}
XFAIL_PREFILTER: dict[tuple[str, str], str] = {}
XFAIL_PRESCREEN: dict[tuple[str, str], str] = {}
XFAIL_SENIORITY: dict[tuple[str, str], str] = {}


def _params(kind: str, xfails: dict):
    for name, prof in PROFESSIONS.items():
        for item in prof[kind]:
            title = item["title"] if isinstance(item, dict) else item
            reason = xfails.get((name, title))
            marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
            yield pytest.param(name, item, marks=marks, id=f"{name}-{title}")


def _keywords_only(config: dict) -> dict:
    return {k: v for k, v in config.items() if k != "topic_terms"}


def test_every_profession_has_the_agreed_shape():
    assert set(PROFESSIONS) == {"software_engineer", "researcher", "accountant", "nurse", "shop_sales", "electrician"}
    for name, prof in PROFESSIONS.items():
        config = prof["config"]
        for key in ("role_targets", "search_keywords", "topic_terms", "exclude"):
            assert config[key], (name, key)
        assert config["location"] == "Copenhagen" and config["languages"] == ["English", "Danish"]
        assert config["remote"] == ("no" if name in ("nurse", "shop_sales", "electrician") else "hybrid")
        assert 6 <= len(prof["on_topic"]) <= 10 and 3 <= len(prof["off_topic"]) <= 5
        assert 3 <= len(prof["postings"]) <= 4 and prof["profile_terms"]
        assert any(p.get("title_en") for p in prof["postings"]), name
        for term in config["topic_terms"]:
            assert term.lower() not in {"manager", "engineer", "specialist", "officer", "advisor"}, (name, term)
        assert not re.search(r"https?://(?!example\.com)|@(?!example)", json.dumps(prof, default=sorted, ensure_ascii=False))
    assert "Fysioterapeut" in PROFESSIONS["researcher"]["off_topic"]
    assert "Key Account Manager" in PROFESSIONS["accountant"]["off_topic"]
    assert any("butik i" in t for t in PROFESSIONS["shop_sales"]["on_topic"])  # an employer-branded title
    assert all(p.get("live_gap") is None or len(p["live_gap"]) == 2 for p in PROFESSIONS.values())


@pytest.mark.parametrize("name, title", _params("on_topic", XFAIL_TOPIC))
def test_on_topic_title_is_kept(name, title):
    config = PROFESSIONS[name]["config"]
    assert title_fit.on_topic(title, title_fit.topic_terms(config)), title


@pytest.mark.parametrize("name, title", _params("off_topic", XFAIL_OFF_TOPIC))
def test_off_topic_title_is_dropped(name, title):
    config = PROFESSIONS[name]["config"]
    assert not title_fit.on_topic(title, title_fit.topic_terms(config)), title


@pytest.mark.parametrize("name, title", _params("on_topic", XFAIL_KEYWORDS_ONLY))
def test_keywords_only_fallback_keeps_on_topic_title(name, title):
    if (name, title) in TOPIC_TERMS_ONLY:
        pytest.skip("only explicit topic_terms name an institute or a store")
    config = _keywords_only(PROFESSIONS[name]["config"])
    assert title_fit.on_topic(title, title_fit.topic_terms(config)), title


@pytest.mark.parametrize("name, title", _params("off_topic", XFAIL_OFF_KEYWORDS_ONLY))
def test_keywords_only_fallback_drops_off_topic_title(name, title):
    config = _keywords_only(PROFESSIONS[name]["config"])
    assert not title_fit.on_topic(title, title_fit.topic_terms(config)), title


def _postings():
    for name, prof in PROFESSIONS.items():
        for posting in prof["postings"]:
            yield name, posting


def _posting_params(xfails):
    for name, posting in _postings():
        reason = xfails.get((name, posting["title"]))
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        yield pytest.param(name, posting, marks=marks, id=f"{name}-{posting['title']}-{posting['location']}")


@pytest.mark.parametrize("name, posting", _posting_params(XFAIL_PREFILTER))
def test_prefilter_keeps_the_professions_postings(name, posting, tmp_path):
    config = PROFESSIONS[name]["config"]
    path = tmp_path / "jobindex" / f"{posting['id']}.json"
    path.parent.mkdir()
    path.write_text(json.dumps(posting))
    assert prefilter.prefilter(tmp_path, config) == [path]


@pytest.mark.parametrize("name, posting", _posting_params(XFAIL_PRESCREEN))
def test_prescreen_score_reaches_the_cutoff(name, posting):
    config = {**PROFESSIONS[name]["config"], "prescreen_min": 0.15}
    score = prescreen.prescreen_score(posting, PROFESSIONS[name]["profile_terms"], config)
    assert score >= config["prescreen_min"], score


def _rank_params():
    for name, prof in PROFESSIONS.items():
        for title in prof["rank_titles"]:
            reason = XFAIL_SENIORITY.get((name, title))
            marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
            yield pytest.param(name, title, marks=marks, id=f"{name}-{title}")


@pytest.mark.parametrize("name, title", _rank_params())
def test_field_rank_words_are_no_seniority_mismatch(name, title):
    targets = PROFESSIONS[name]["config"]["role_targets"]
    score = prescreen._seniority_match(title, targets, "da")
    assert score != 0.0
    if name == "researcher":
        assert score == 1.0   # every academic rank is one level (#431)


def test_every_xfail_cites_an_open_subissue():
    tables = [XFAIL_TOPIC, XFAIL_KEYWORDS_ONLY, XFAIL_OFF_TOPIC, XFAIL_OFF_KEYWORDS_ONLY, XFAIL_PREFILTER,
              XFAIL_PRESCREEN, XFAIL_SENIORITY]
    for table in tables:
        for key, reason in table.items():
            numbers = {int(n) for n in re.findall(r"#(\d+)", reason)}
            assert numbers and numbers <= OPEN_SUBISSUES, (key, reason)


def test_an_institute_name_is_topic_evidence_for_a_title_with_no_field_word():
    terms = title_fit.topic_terms(PROFESSIONS["researcher"]["config"])
    assert title_fit.on_topic("Tenure-track Position, Niels Bohr Institute", terms)
    assert title_fit.on_topic("Researcher, Institut for Fysik og Astronomi", terms)
    without = [t for t in terms if "institut" not in t.lower() and "department" not in t.lower()]
    assert not title_fit.on_topic("Tenure-track Position, Niels Bohr Institute", without)
