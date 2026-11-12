"""`jobs/discovery/<source>.json`: when LinkedIn employer discovery last ran, when it refused,
and which employers it has already looked at. Pure and offline (tmp_path)."""

import json
from datetime import datetime, timedelta, timezone

from door.core import discovery_state as ds

NOW = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)


def test_a_missing_or_broken_file_is_an_empty_state(tmp_path):
    assert ds.load(tmp_path, "linkedin") == {"seen": {}}
    (tmp_path / "discovery").mkdir()
    (tmp_path / "discovery" / "linkedin.json").write_text("not json")
    assert ds.load(tmp_path, "linkedin") == {"seen": {}}


def test_save_then_load_round_trips_atomically(tmp_path):
    state = {"last_run": NOW.isoformat(), "seen": {"bec": {"outcome": "suggested", "at": NOW.isoformat()}}}
    ds.save(tmp_path, "linkedin", state)
    assert json.loads((tmp_path / "discovery" / "linkedin.json").read_text()) == state
    assert ds.load(tmp_path, "linkedin") == state
    assert not list(tmp_path.glob("*.tmp"))


def test_since_is_the_last_run_minus_a_day_never_beyond_max_age():
    state = {"last_run": (NOW - timedelta(days=7)).isoformat(), "seen": {}}
    assert ds.since(state, 30, NOW) == NOW - timedelta(days=7)  # a week at most: who is hiring now
    assert ds.since({**state, "last_run": (NOW - timedelta(days=2)).isoformat()}, 30, NOW) == NOW - timedelta(days=3)
    assert ds.since(state, 3, NOW) == NOW - timedelta(days=3)
    assert ds.since({"seen": {}}, 30, NOW) == NOW - timedelta(days=7)
    assert ds.since({"seen": {}}, 2, NOW) == NOW - timedelta(days=2)
    assert ds.since({"seen": {}}, None, NOW) == NOW - timedelta(days=7)


def test_rests_a_day_after_a_pushback():
    state = {"pushback_at": NOW.isoformat(), "seen": {}}
    assert ds.resting_until(state, NOW + timedelta(hours=23), "linkedin") == NOW + timedelta(hours=24)
    assert ds.resting_until(state, NOW + timedelta(hours=24), "linkedin") is None
    assert ds.resting_until({"seen": {}}, NOW, "linkedin") is None


def test_known_companies_are_the_seen_ones_younger_than_90_days():
    state = {"seen": {
        "bec": {"outcome": "unresolved", "at": (NOW - timedelta(days=89)).isoformat()},
        "old co": {"outcome": "easy_apply", "at": (NOW - timedelta(days=91)).isoformat()},
        "broken": {"outcome": "easy_apply"},
    }}
    assert ds.known(state, NOW) == {"bec"}


def test_record_run_marks_employers_and_clears_the_pushback():
    state = {"pushback_at": NOW.isoformat(), "seen": {}}
    ds.record(state, "BEC Group", "suggested", NOW)
    ds.finish(state, NOW)
    assert state["seen"] == {"bec group": {"outcome": "suggested", "at": NOW.isoformat()}}
    assert state["last_run"] == NOW.isoformat() and "pushback_at" not in state


def test_a_refusal_stamps_the_pushback_and_keeps_last_run():
    state = {"last_run": "2026-10-01T00:00:00+00:00", "seen": {}}
    ds.refused(state, NOW)
    assert state["pushback_at"] == NOW.isoformat() and state["last_run"] == "2026-10-01T00:00:00+00:00"


# --------------------------------------------------------------------------- #
# pace: the request budget and pause that adapt to what LinkedIn tolerates
# --------------------------------------------------------------------------- #

def _run(state, outcome="ok", *, requests=10, first_429=None, at=NOW):
    ds.record_run(state, at, mode="combined", requests=requests, pages=requests, job_pages=0, outcome=outcome,
                  seconds=900.0, first_429=first_429)


def test_a_fresh_state_paces_at_the_defaults():
    pace = ds.pace({"seen": {}})
    assert pace == {"budget": ds.DEFAULT_BUDGET, "factor": 1, "pause": ds.BASE_PAUSE}
    assert ds.DEFAULT_BUDGET == 150 and ds.BASE_PAUSE == (2.0, 4.0)


def test_a_refusal_halves_the_budget_and_doubles_the_pause():
    state = {"seen": {}}
    _run(state, "refused", requests=7, first_429={"after_requests": 7, "after_s": 640})
    assert ds.pace(state) == {"budget": 75, "factor": 2, "pause": (4.0, 8.0)}
    _run(state, "refused")
    assert ds.pace(state) == {"budget": 37, "factor": 4, "pause": (8.0, 16.0)}


def test_the_pace_stops_at_its_floor_and_ceiling():
    state = {"seen": {}}
    for _ in range(8):
        _run(state, "refused")
    assert ds.pace(state)["budget"] == ds.MIN_BUDGET and ds.pace(state)["factor"] == ds.MAX_FACTOR


def test_three_clean_runs_in_a_row_step_back_toward_the_defaults():
    state = {"seen": {}}
    _run(state, "refused")
    _run(state, "refused")
    _run(state)
    _run(state, "budget")
    assert ds.pace(state)["factor"] == 4  # two clean runs are not enough
    _run(state)
    assert ds.pace(state) == {"budget": 74, "factor": 2, "pause": (4.0, 8.0)}
    for _ in range(3):
        _run(state)
    assert ds.pace(state) == {"budget": 148, "factor": 1, "pause": ds.BASE_PAUSE}
    for _ in range(6):
        _run(state)
    assert ds.pace(state)["budget"] == ds.DEFAULT_BUDGET  # never above the default


def test_an_error_or_a_refusal_breaks_the_clean_streak():
    state = {"seen": {}}
    _run(state, "refused")
    _run(state)
    _run(state)
    _run(state, "error")
    _run(state)
    _run(state)
    assert ds.pace(state)["factor"] == 2  # the streak restarted


def test_a_run_without_requests_neither_counts_as_clean_nor_is_logged():
    state = {"seen": {}}
    _run(state, "refused")
    for _ in range(5):
        _run(state, requests=0)
    assert ds.pace(state)["factor"] == 2 and len(state["history"]) == 1


def test_every_run_is_logged_with_what_it_observed_and_only_the_last_thirty_are_kept():
    state = {"seen": {}}
    _run(state, "refused", requests=7, first_429={"after_requests": 7, "after_s": 640}, at=NOW)
    entry = state["history"][0]
    assert entry == {"at": NOW.isoformat(), "mode": "combined", "requests": 7, "pages": 7, "job_pages": 0,
                     "budget": 150, "pause": [2.0, 4.0], "outcome": "refused", "seconds": 900.0,
                     "first_429": {"after_requests": 7, "after_s": 640}}
    for i in range(40):
        _run(state, at=NOW + timedelta(minutes=i + 1))
    assert len(state["history"]) == ds.HISTORY_KEEP and state["history"][-1]["at"] == (NOW + timedelta(minutes=40)).isoformat()


def test_a_garbled_pace_falls_back_to_the_defaults():
    assert ds.pace({"seen": {}, "pace": {"budget": "x", "factor": 99}})["budget"] == ds.DEFAULT_BUDGET
    assert ds.pace({"seen": {}, "pace": {"budget": 1, "factor": 0}}) == {
        "budget": ds.MIN_BUDGET, "factor": 1, "pause": ds.BASE_PAUSE}


# --------------------------------------------------------------------------- #
# search mode and the rotation of keywords
# --------------------------------------------------------------------------- #

def test_the_search_mode_is_the_module_default_unless_the_state_overrides_it():
    assert ds.search_mode({"seen": {}}) == ds.SEARCH_MODE == "rotate"
    assert ds.search_mode({"seen": {}, "mode": "combined"}) == "combined"
    assert ds.search_mode({"seen": {}, "mode": "nonsense"}) == "rotate"


def test_the_rotation_takes_a_few_keywords_round_robin():
    kws = ["a", "b", "c", "d", "e"]
    state = {"seen": {}}
    assert ds.rotation(state, kws, 2) == ["a", "b"]
    ds.advance_rotation(state, kws, 2)
    assert ds.rotation(state, kws, 2) == ["c", "d"]
    ds.advance_rotation(state, kws, 2)
    assert ds.rotation(state, kws, 2) == ["e", "a"]  # wraps
    ds.advance_rotation(state, kws, 2)
    assert ds.rotation(state, kws, 2) == ["b", "c"]
    assert ds.rotation({"seen": {}, "rotation": 99}, kws, 2) == ["e", "a"]  # an index past the end is taken modulo
    assert ds.rotation(state, ["a"], 3) == ["a"]


def test_a_searched_keyword_remembers_when_so_the_next_search_reaches_back_to_it():
    state = {"seen": {}}
    assert ds.keyword_since(state, "Data Scientist", 30, NOW) == NOW - timedelta(days=7)
    ds.mark_searched(state, "Data Scientist", NOW - timedelta(days=4))
    assert ds.keyword_since(state, "data scientist", 30, NOW) == NOW - timedelta(days=5)
    assert ds.keyword_since(state, "data scientist", 2, NOW) == NOW - timedelta(days=2)


def test_a_cancelled_run_is_logged_but_leaves_the_pace_and_the_streak_alone():
    state = {"seen": {}}
    _run(state, "refused")
    _run(state)
    _run(state, "cancelled")
    assert ds.pace(state)["factor"] == 2 and state["pace"]["clean_runs"] == 1 and len(state["history"]) == 3


# --- per-source files and the migration of the old single file ---------------------------------------------------

def test_each_source_has_its_own_file(tmp_path):
    ds.save(tmp_path, "linkedin", {"seen": {}, "mode": "rotate"})
    ds.save(tmp_path, "fake", {"seen": {}, "mode": "combined"})
    assert ds.load(tmp_path, "linkedin")["mode"] == "rotate" and ds.load(tmp_path, "fake")["mode"] == "combined"
    assert ds.path(tmp_path, "fake") == tmp_path / "discovery" / "fake.json"


def test_the_old_linkedin_file_is_migrated_by_copy_on_load_and_kept(tmp_path):
    old = {"last_run": NOW.isoformat(), "seen": {}, "pace": {"budget": 75, "factor": 2, "clean_runs": 0}}
    (tmp_path / "linkedin_discovery.json").write_text(json.dumps(old))
    assert ds.load(tmp_path, "linkedin") == old
    assert json.loads((tmp_path / "discovery" / "linkedin.json").read_text()) == old
    assert (tmp_path / "linkedin_discovery.json").exists()
    assert ds.load(tmp_path, "linkedin") == old  # idempotent


def test_the_new_file_wins_when_both_exist(tmp_path):
    (tmp_path / "linkedin_discovery.json").write_text(json.dumps({"mode": "combined", "seen": {}}))
    ds.save(tmp_path, "linkedin", {"mode": "rotate", "seen": {}})
    assert ds.load(tmp_path, "linkedin")["mode"] == "rotate"


def test_another_source_never_reads_the_legacy_file(tmp_path):
    (tmp_path / "linkedin_discovery.json").write_text(json.dumps({"mode": "combined", "seen": {}}))
    assert ds.load(tmp_path, "fake") == {"seen": {}}
    assert not (tmp_path / "discovery" / "fake.json").exists()


def test_resting_is_read_for_any_source():
    assert ds.resting_until({"pushback_at": NOW.isoformat(), "seen": {}}, NOW, "fake") == NOW + timedelta(hours=24)
