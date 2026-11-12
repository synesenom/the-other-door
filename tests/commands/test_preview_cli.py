"""The first look (`_preview_core`, the `preview_matches` tool and `init`): a handful of ads of one board, scored
right after the sources are read and before anything is saved. Leaves no trace in `jobs/`.

Offline: the board's scraper and the scorer are replaced.
"""

import asyncio
import types
from datetime import datetime, timedelta, timezone

import pytest

import door.mcp_server as server
from door import scrapers
from door.commands import preview as preview_cmd
from door.core import sites, workspace
from door.matching import scorer
from paths import REPO_ROOT

CONFIG = {
    "location": "Copenhagen", "role_targets": ["Data Scientist"], "search_keywords": ["data scientist", "ml engineer"],
    "topic_terms": ["data"], "languages": ["English"], "remote": "hybrid",
}
CV = "# Jane Doe\n\nData scientist.\n"


def _ad(i, title="Data Scientist", **fields):
    return {"id": f"jobindex.{i}", "title": title, "company": f"Co {i}", "location": "Copenhagen", "url": f"https://x/{i}", **fields}


@pytest.fixture
def env(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", REPO_ROOT / "profile.example")
    return types.SimpleNamespace(jobs_dir=jobs_dir, seen={}, ads=[_ad(i) for i in range(1, 4)], scored=[])


@pytest.fixture
def board(env, monkeypatch):
    def fake_scrape(site, config, since=None):
        env.seen.update(site=site, config=config, since=since)
        return iter(env.ads)
    monkeypatch.setattr(preview_cmd, "_board_records", fake_scrape)
    return env


@pytest.fixture
def scored(board, monkeypatch):
    def fake_score(postings, *, system_prompt, **kw):
        board.scored.append(list(postings))
        board.seen["system_prompt"] = system_prompt
        return {p["id"]: {"score": 0.5 + int(p["id"][-1]) / 10, "score_reason": f"reason {p['id']}"} for p in postings}, []
    monkeypatch.setattr(scorer, "score_postings", fake_score)
    return board


def test_it_reads_the_first_board_with_one_keyword_and_seven_days(scored):
    before = datetime.now(timezone.utc)
    result = preview_cmd._preview_core(CONFIG, CV)
    assert result["board"] == "jobindex"
    config = scored.seen["config"]
    assert config["search_keywords"] == ["data scientist"] and config["_mode"] == "search" and config["_country"] == "dk"
    assert before - timedelta(days=7, seconds=5) < scored.seen["since"] < datetime.now(timezone.utc)


def test_it_returns_the_matches_best_first_and_says_where_from(scored):
    matches = preview_cmd._preview_core(CONFIG, CV)["matches"]
    assert [m["title"] for m in matches] == ["Data Scientist"] * 3
    assert [m["score"] for m in matches] == [0.8, 0.7, 0.6]
    assert matches[0] == {
        "title": "Data Scientist", "company": "Co 3", "location": "Copenhagen", "score": 0.8,
        "score_reason": "reason jobindex.3", "url": "https://x/3",
    }


def test_the_candidate_is_the_cv_and_answers_given_not_a_profile(scored):
    preview_cmd._preview_core(CONFIG, CV)
    assert "Data scientist." in scored.seen["system_prompt"] and "Copenhagen" in scored.seen["system_prompt"]


def test_only_titles_on_topic_are_scored_at_most_the_limit(scored):
    scored.ads = [_ad(1, "Chef"), _ad(2, "Baker"), *[_ad(i) for i in range(3, 9)]]
    preview_cmd._preview_core(CONFIG, CV, limit=2)
    assert [p["id"] for p in scored.scored[0]] == ["jobindex.3", "jobindex.4"]


def test_it_stops_reading_the_board_at_the_limit(board, monkeypatch):
    read = []

    def records():
        for ad in [_ad(i) for i in range(1, 100)]:
            read.append(ad["id"])
            yield ad

    monkeypatch.setattr(preview_cmd, "_board_records", lambda *a, **k: records())
    monkeypatch.setattr(scorer, "score_postings", lambda postings, **k: ({}, []))
    preview_cmd._preview_core(CONFIG, CV, limit=2)
    assert len(read) == 2


def test_seen_only_records_are_skipped(scored):
    scored.ads = [{"platform_id": "1", "seen_only": True}, _ad(2)]
    assert len(preview_cmd._preview_core(CONFIG, CV)["matches"]) == 1


def test_it_leaves_no_trace_in_jobs(scored):
    preview_cmd._preview_core(CONFIG, CV)
    assert not scored.jobs_dir.exists()


def test_a_scraper_error_is_a_warning(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("board is down")
    monkeypatch.setattr(preview_cmd, "_board_records", boom)
    result = preview_cmd._preview_core(CONFIG, CV)
    assert result["matches"] == [] and "board is down" in result["warning"] and "error" not in result


def test_no_ads_on_topic_is_a_warning(scored):
    scored.ads = [_ad(1, "Chef")]
    result = preview_cmd._preview_core(CONFIG, CV)
    assert result["matches"] == [] and result["board"] == "jobindex" and "warning" in result
    assert scored.scored == []


def test_a_failed_scoring_is_a_warning(board, monkeypatch):
    monkeypatch.setattr(scorer, "score_postings", lambda postings, **k: ({}, [p["id"] for p in postings]))
    result = preview_cmd._preview_core(CONFIG, CV)
    assert result["matches"] == [] and "warning" in result


def test_no_board_for_the_city_is_a_warning(env, monkeypatch):
    monkeypatch.setattr(sites, "boards_for_location", lambda location: [])
    result = preview_cmd._preview_core(CONFIG, CV)
    assert result["matches"] == [] and "warning" in result


def test_no_cv_is_a_warning_and_no_call(env, monkeypatch):
    monkeypatch.setattr(preview_cmd, "_board_records", lambda *a, **k: pytest.fail("no CV, no scraping"))
    result = preview_cmd._preview_core(CONFIG, None)
    assert result["matches"] == [] and "warning" in result


def test_no_keyword_is_a_warning(env, monkeypatch):
    monkeypatch.setattr(preview_cmd, "_board_records", lambda *a, **k: pytest.fail("no keyword, no scraping"))
    result = preview_cmd._preview_core({"location": "Copenhagen"}, CV)
    assert result["matches"] == [] and "warning" in result


def test_board_records_call_the_sites_module(monkeypatch):
    fake = types.SimpleNamespace(iter_scrape=lambda config, known_ids, since: iter([_ad(1)]))
    monkeypatch.setattr(preview_cmd.importlib, "import_module", lambda name: fake)
    assert list(preview_cmd._board_records("jobindex", {}, since=None))[0]["id"] == "jobindex.1"
    fake = types.SimpleNamespace(scrape=lambda config, known_ids, since: [_ad(2)])
    monkeypatch.setattr(preview_cmd.importlib, "import_module", lambda name: fake)
    assert list(preview_cmd._board_records("jobindex", {}, since=None))[0]["id"] == "jobindex.2"


def test_board_errors_recorded_by_the_scraper_do_not_stay_for_the_real_run(scored):
    scrapers.record_error("jobindex", "a page failed")
    preview_cmd._preview_core(CONFIG, CV)
    assert not scrapers.drain_errors("jobindex")


def test_tool_builds_the_config_from_the_answers(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(preview_cmd, "_preview_core", lambda config, cv, *, limit, **k: seen.update(config=config, cv=cv, limit=limit) or {"matches": []})
    (env.jobs_dir.parent / "profile").mkdir()
    (env.jobs_dir.parent / "profile" / "cv.draft.md").write_text(CV)
    result = asyncio.run(server.preview_matches("Copenhagen", ["Data Scientist"], search_keywords=["data"], topic_terms=["ml"], languages=["Danish"], remote="yes"))
    assert result == {"matches": []}
    assert seen["config"] == {
        "location": "Copenhagen", "role_targets": ["Data Scientist"], "search_keywords": ["data"], "topic_terms": ["ml"],
        "languages": ["Danish"], "remote": "yes",
    }
    assert seen["cv"] == CV.strip() and seen["limit"] == 5
