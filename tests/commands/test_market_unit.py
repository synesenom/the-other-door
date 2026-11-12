"""`market`: counting what scraped ads ask for. Pure helpers plus `_market_core` on a fixture tree."""

import json
import time
from datetime import datetime, timezone

import pytest

from door.commands import market as market_cmd
from door.core import claude_cli, lock
from cli_utils import write_list_posting
from profile_utils import write_config

@pytest.fixture(autouse=True)
def _no_real_claude(monkeypatch):
    def refuse(*a, **k):
        raise claude_cli.ClaudeError("claude is not available in tests")

    monkeypatch.setattr(claude_cli, "ask", refuse)


NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _p(id_="a", **kw):
    d = {"id": id_, "title": "Data Engineer", "company": "Acme", "posted_at": "2026-10-20T00:00:00+00:00"}
    d.update(kw)
    return d


def _scored(id_="a", score=0.8, matching=(), missing=(), **kw):
    return _p(id_, score=score, score_reason="fits", scored_by="haiku", matching_skills=list(matching), missing_skills=list(missing), **kw)


def test_window_uses_posted_at_else_scraped_at():
    assert market_cmd._when({"posted_at": "2026-10-01", "scraped_at": "2026-09-01"}) == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert market_cmd._when({"scraped_at": "2026-09-01T00:00:00+00:00"}) == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert market_cmd._when({"posted_at": "garbage"}) is None


def test_naive_and_aware_timestamps_compare():
    a = market_cmd._when({"posted_at": "2026-10-01T00:00:00"})
    b = market_cmd._when({"posted_at": "2026-10-01T00:00:00+00:00"})
    assert a == b


def test_duplicates_are_not_counted():
    assert market_cmd._is_duplicate({"duplicate_of": "x"})
    assert market_cmd._is_duplicate({"score_reason": "duplicate"})
    assert not market_cmd._is_duplicate(_p())


@pytest.mark.parametrize(
    "reason", ["duplicate", "excluded", "prefilter:title", "prescreen:x", "language: de not in languages", "no description"]
)
def test_scored_excludes_hard_zeros(reason):
    assert not market_cmd._is_scored({"score": 0.0, "score_reason": reason})


def test_scored_means_the_scorer_read_it():
    assert not market_cmd._is_scored({})
    assert not market_cmd._is_scored({"score": 0.4, "score_reason": "ok"})
    assert market_cmd._is_scored({"score": 0.4, "score_reason": "ok", "scored_by": "haiku"})
    assert not market_cmd._is_scored({"score": 0.0, "score_reason": "duplicate", "scored_by": "haiku", "duplicate_of": "a"})


def test_previous_window_is_the_days_before():
    cur = _scored("c", posted_at="2026-10-20")
    prev = _scored("p", posted_at="2026-09-20")
    old = _scored("o", posted_at="2026-07-01")
    dup = _scored("d", posted_at="2026-10-20", duplicate_of="c")
    raw, scored, prev_scored = market_cmd._split_windows([cur, prev, old, dup], NOW, 30)
    assert [p["id"] for p in raw] == ["c"]
    assert [p["id"] for p in scored] == ["c"]
    assert [p["id"] for p in prev_scored] == ["p"]


def test_count_skills_counts_shares_case_insensitive():
    scored = [_scored("1", matching=["Python"], missing=["dbt"]), _scored("2", matching=["python"]), _scored("3", missing=["DBT"])]
    rows = market_cmd._count_skills(scored, [])
    by = {r["name"].lower(): r for r in rows}
    assert by["python"]["count"] == 2 and by["python"]["share"] == pytest.approx(2 / 3)
    assert by["dbt"]["count"] == 2
    assert rows[0]["count"] >= rows[1]["count"]


def test_have_matching_more_often_than_missing_tie_is_not_had():
    scored = [_scored("1", matching=["A", "B"], missing=["B", "C"]), _scored("2", matching=["A"], missing=["C"])]
    by = {r["name"]: r for r in market_cmd._count_skills(scored, [])}
    assert by["A"]["have"] is True
    assert by["B"]["have"] is False
    assert by["C"]["have"] is False


def test_trend_none_below_50_scored_in_either_window():
    cur = [_scored(str(i), matching=["X"]) for i in range(50)]
    prev = [_scored(str(i), matching=["X"]) for i in range(49)]
    assert market_cmd._count_skills(cur, prev)[0]["trend"] is None
    assert market_cmd._count_skills(prev, cur)[0]["trend"] is None


def test_trend_delta_with_50_in_both_windows():
    cur = [_scored(str(i), matching=["X"] if i < 30 else []) for i in range(50)]
    prev = [_scored(str(i), matching=["X"] if i < 20 else []) for i in range(50)]
    assert market_cmd._count_skills(cur, prev)[0]["trend"] == 10


def test_skills_limited_to_15():
    scored = [_scored("1", matching=[f"s{i}" for i in range(30)])]
    assert len(market_cmd._count_skills(scored, [])) == 15


def test_near_misses_band_inclusive_low_exclusive_high():
    scored = [
        _scored("lo", score=0.35, missing=["dbt"]),
        _scored("mid", score=0.45, missing=["dbt", "Spark"]),
        _scored("at", score=0.5, missing=["dbt"]),
        _scored("far", score=0.3, missing=["dbt"]),
    ]
    nm = market_cmd._near_misses(scored, 0.5)
    assert nm["n"] == 2
    assert nm["rows"] == [{"skill": "dbt", "count": 2}, {"skill": "Spark", "count": 1}]
    assert "language" not in nm


def test_near_miss_rows_limited_to_10():
    scored = [_scored("1", score=0.45, missing=[f"s{i}" for i in range(20)])]
    assert len(market_cmd._near_misses(scored, 0.5)["rows"]) == 10


def test_companies_repeat_at_least_two_top_10():
    raw = [_p(str(i), company="Acme") for i in range(3)] + [_p("x", company="Solo")] + [_p("y1", company="Pleo"), _p("y2", company="pleo")]
    assert market_cmd._companies(raw) == [{"name": "Acme", "count": 3}, {"name": "Pleo", "count": 2}]


def test_mark_followed_matches_names_like_the_employer_list():
    from door.core import companies as store

    items = [store.Company(name="Novo Nordisk", feed=store.Feed(platform="greenhouse", id="novo"), status="followed", found_via="manual"),
             store.Company(name="Pleo", status="dormant", found_via="manual")]
    rows = market_cmd._mark_followed([{"name": "Novo Nordisk A/S", "count": 3}, {"name": "Pleo", "count": 2}, {"name": "Acme", "count": 2}], items)
    assert [r["followed"] for r in rows] == [True, False, False]


def test_uncovered_titles_over_matches_case_insensitive():
    matches = [_scored("1", title="Analytics Engineer"), _scored("2", title="analytics engineer"), _scored("3", title="Senior Data Engineer")]
    assert market_cmd._uncovered_titles(matches, ["data engineer"]) == [{"title": "Analytics Engineer", "count": 2}]


# ---- core ------------------------------------------------------------------

@pytest.fixture
def tree(tmp_path):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile, {"role_targets": ["Data Engineer"], "search_keywords": ["data engineer"], "min_score": 0.5})
    def w(i, date="2026-10-20", **kw):
        write_list_posting(jobs, date, "jobindex", i, **kw)
    w("a", title="Data Engineer", company="Acme", posted_at="2026-10-20T00:00:00+00:00", score=0.8, score_reason="ok", scored_by="haiku", matching_skills=["Python"], missing_skills=["dbt"])
    w("b", title="Analytics Engineer", company="Acme", posted_at="2026-10-21T00:00:00+00:00", score=0.7, score_reason="ok", scored_by="haiku", matching_skills=["Python"], missing_skills=["dbt"])
    w("c", title="Data Engineer", company="Beta", posted_at="2026-10-22T00:00:00+00:00", score=0.4, score_reason="ok", scored_by="haiku", missing_skills=["dbt"])
    w("d", title="Data Engineer", company="Beta", posted_at="2026-10-22T00:00:00+00:00")
    w("e", title="Data Engineer", company="Beta", posted_at="2026-10-22T00:00:00+00:00", score=0.0, score_reason="duplicate", duplicate_of="a")
    w("f", date="2026-09-20", posted_at="2026-09-20T00:00:00+00:00", score=0.9, score_reason="ok", scored_by="haiku", matching_skills=["Python"])
    w("g", date="2026-10-24", scraped_at="2026-10-24T00:00:00+00:00", posted_at=None)
    return profile, jobs


def _core(tree, **kw):
    profile, jobs = tree
    kw.setdefault("now", NOW)
    return market_cmd._market_core(profile_dir=profile, jobs_dir=jobs, **kw)


def test_market_core_shape_and_counts(tree):
    r = _core(tree, save=False)
    assert r["counts"] == {"scraped": 5, "scored": 3, "above_min_score": 2}
    assert r["window"]["days"] == 30
    assert set(r) >= {"window", "counts", "skills", "near_misses", "uncovered_titles", "companies"}
    assert "language" not in r and "location" not in r
    assert r["near_misses"]["n"] == 1
    assert r["uncovered_titles"] == [{"title": "Analytics Engineer", "count": 1}]
    assert r["companies"]["population"] == "scraped"
    assert r["companies"]["rows"][0] == {"name": "Acme", "count": 3, "followed": False}
    assert r["skills"][0]["trend"] is None
    assert r["report_path"] is None
    # the desktop app's Today reads it this way: no report is written
    assert not list(tree[1].rglob("report-*.md"))


def test_scored_companies_counts_scored_ads_only(tree):
    r = _core(tree, save=False, scored_companies=True)
    assert r["companies"]["population"] == "scored"
    assert r["companies"]["rows"] == [{"name": "Acme", "count": 2, "followed": False}]
    assert "(scored ads)" in market_cmd.render_markdown(r)


def test_followed_company_is_marked(tree):
    from door.core import companies as store

    store.save(tree[0], [store.Company(name="Acme", feed=store.Feed(platform="greenhouse", id="acme"), status="followed", found_via="manual")])
    r = _core(tree, save=False)
    assert r["companies"]["rows"][0]["followed"] is True
    text = market_cmd.render_markdown(r)
    assert "Acme (3) ✓ followed" in text and "Beta (2)" in text and "Beta (2) ✓" not in text


def test_market_core_no_save_writes_nothing(tree):
    _core(tree, save=False)
    assert not (tree[1] / "market").exists()


def test_market_core_days_lt_1_raises(tree):
    with pytest.raises(ValueError):
        _core(tree, days=0)


def test_market_core_empty_jobs_dir(tmp_path):
    r = market_cmd._market_core(profile_dir=tmp_path / "p", jobs_dir=tmp_path / "j", save=False, now=NOW)
    assert r["counts"] == {"scraped": 0, "scored": 0, "above_min_score": 0}


def test_render_markdown_sections_and_trend_hidden(tree):
    text = market_cmd.render_markdown(_core(tree, save=False))
    assert text.startswith("# Market")
    assert "5 ads scraped, 3 scored, 2 above min_score" in text
    assert "Python" in text and "✓" in text and "✗" in text
    assert "trend" not in text
    assert "Near misses" in text and "dbt" in text and "in 1 of 1" in text
    assert "Analytics Engineer" in text
    assert "Companies posting repeatedly (scraped ads)" in text and "Acme (3)" in text
    assert "Language" not in text and "Location" not in text


def test_save_writes_report_and_takes_the_lock(tree, monkeypatch):
    purposes = []
    real = lock.ledger_lock

    def spy(jobs_dir, purpose):
        purposes.append(purpose)
        return real(jobs_dir, purpose)

    monkeypatch.setattr(lock, "ledger_lock", spy)
    r = _core(tree)
    path = tree[1] / "market" / "report-2026-10-26.md"
    assert r["report_path"] == str(path)
    assert path.read_text() == market_cmd.render_markdown(r)
    assert purposes == ["market"]


def test_market_runs_fast_on_month_of_postings(tmp_path):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile, {"role_targets": ["Data Engineer"], "min_score": 0.5})
    for i in range(1800):
        write_list_posting(jobs, "2026-10-20", "jobindex", f"j{i}", posted_at="2026-10-20T00:00:00+00:00",
                           score=0.6, score_reason="ok", scored_by="haiku", matching_skills=["Python"], missing_skills=[f"s{i % 40}"])
    start = time.monotonic()
    market_cmd._market_core(profile_dir=profile, jobs_dir=jobs, save=False, now=NOW)
    assert time.monotonic() - start < 5


# ---- skill aliases (#242) ----------------------------------------------------

def _aliases_path(tree):
    return tree[1] / "skill_aliases.json"


def _write_aliases(tree, data):
    _aliases_path(tree).write_text(json.dumps(data), encoding="utf-8")


def _answer(groups):
    return {"groups": [{"variant": v, "canonical": c, "skill": k} for v, c, k in groups]}


def _fake_ask(monkeypatch, handler):
    calls = []

    def fake(system_prompt, input, **kw):
        calls.append({"system": system_prompt, "input": input, **kw})
        return handler(len(calls), input, kw)

    monkeypatch.setattr(claude_cli, "ask", fake)
    return calls


def _names_in(call):
    return json.loads(call["input"])["names"]


def test_normalise_maps_case_insensitively_dedupes_drops_null_keeps_unknown():
    aliases = {"aws": "AWS", "amazon web services": "AWS", "aws (lambda, s3)": "AWS", "fluent english": None}
    out = market_cmd._normalise(["Amazon Web Services", "aws", "AWS (Lambda, S3)", "Fluent English", " Rust ", ""], aliases)
    assert out == ["AWS", "Rust"]


def test_unknown_names_are_stripped_case_insensitive_and_cover_both_windows():
    cur = [_scored("1", matching=[" Rust ", "AWS"], missing=["Go"])]
    prev = [_scored("2", matching=["rust", "Zig"])]
    assert market_cmd._unknown_names(cur, prev, {"aws": "AWS"}) == ["Go", "Rust", "Zig"]


def test_three_variants_count_as_one_skill_with_summed_count(tree):
    profile, jobs = tree
    _write_aliases(tree, {"aws": "AWS", "amazon web services": "AWS", "aws (lambda, s3)": "AWS", "python": "Python", "dbt": "dbt"})
    for i, name in enumerate(["AWS", "Amazon Web Services", "AWS (Lambda, S3)"]):
        write_list_posting(jobs, "2026-10-20", "jobindex", f"v{i}", posted_at="2026-10-20T00:00:00+00:00", score=0.8,
                           score_reason="ok", scored_by="haiku", matching_skills=[name], missing_skills=[])
    r = _core(tree, save=False)
    aws = [s for s in r["skills"] if s["name"] == "AWS"]
    assert len(aws) == 1 and aws[0]["count"] == 3 and aws[0]["have"] is True
    assert not [s for s in r["skills"] if "amazon" in s["name"].lower()]


def test_trend_uses_canonical_names_in_both_windows(tree):
    _write_aliases(tree, {"aws": "AWS", "amazon web services": "AWS", "python": "Python", "dbt": "dbt"})
    profile, jobs = tree
    for i in range(50):
        write_list_posting(jobs, "2026-10-20", "jobindex", f"c{i}", posted_at="2026-10-20T00:00:00+00:00", score=0.8,
                           score_reason="ok", scored_by="haiku", matching_skills=["AWS"])
        write_list_posting(jobs, "2026-09-20", "jobindex", f"p{i}", posted_at="2026-09-20T00:00:00+00:00", score=0.8,
                           score_reason="ok", scored_by="haiku", matching_skills=["Amazon Web Services"] if i < 20 else [])
    r = _core(tree, save=False)
    assert [s["trend"] for s in r["skills"] if s["name"] == "AWS"] == [30]


def test_near_misses_use_canonical_names(tree):
    _write_aliases(tree, {"dbt": "dbt", "dbt core": "dbt", "python": "Python"})
    write_list_posting(tree[1], "2026-10-20", "jobindex", "nm", posted_at="2026-10-20T00:00:00+00:00", score=0.4,
                       score_reason="ok", scored_by="haiku", missing_skills=["DBT Core"])
    r = _core(tree, save=False)
    assert r["near_misses"]["rows"] == [{"skill": "dbt", "count": 2}]


def test_non_skills_dropped_from_counts(tree):
    _write_aliases(tree, {"python": "Python", "dbt": "dbt", "fluent english": None})
    write_list_posting(tree[1], "2026-10-20", "jobindex", "ns", posted_at="2026-10-20T00:00:00+00:00", score=0.8,
                       score_reason="ok", scored_by="haiku", missing_skills=["Fluent English"])
    r = _core(tree, save=False)
    assert "fluent english" not in [s["name"].lower() for s in r["skills"]]


def test_market_core_makes_no_claude_call_when_all_known(tree, monkeypatch):
    _write_aliases(tree, {"python": "Python", "dbt": "dbt"})
    calls = _fake_ask(monkeypatch, lambda *a: pytest.fail("no call expected"))
    r = _core(tree, save=False)
    assert calls == [] and r["warning"] is None


def test_only_unknown_names_sent_with_existing_canonicals_as_context(tree, monkeypatch):
    _write_aliases(tree, {"python": "Python", "py": "Python", "k8s": "Kubernetes"})
    calls = _fake_ask(monkeypatch, lambda n, i, kw: _answer([("dbt", "dbt", True)]))
    _core(tree, save=False)
    assert len(calls) == 1
    c = calls[0]
    assert _names_in(c) == ["dbt"]
    assert json.loads(c["input"])["known_canonical"] == ["Kubernetes", "Python"]
    assert c["model"] == "haiku" and c["timeout_s"] == 120 and c["profile_dir"] == tree[0]
    props = c["schema"]["properties"]["groups"]["items"]["properties"]
    assert set(props) == {"variant", "canonical", "skill"}


def test_context_is_capped_at_300(tree, monkeypatch):
    _write_aliases(tree, {f"v{i}": f"Canon{i}" for i in range(400)})
    calls = _fake_ask(monkeypatch, lambda n, i, kw: _answer([]))
    _core(tree, save=False)
    assert len(json.loads(calls[0]["input"])["known_canonical"]) == 300


def test_chunks_of_200(tmp_path, monkeypatch):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile, {"role_targets": ["Data Engineer"], "min_score": 0.5})
    write_list_posting(jobs, "2026-10-20", "jobindex", "big", posted_at="2026-10-20T00:00:00+00:00", score=0.8,
                       score_reason="ok", scored_by="haiku", matching_skills=[f"skill{i:03d}" for i in range(450)])
    calls = _fake_ask(monkeypatch, lambda n, i, kw: _answer([]))
    market_cmd._market_core(profile_dir=profile, jobs_dir=jobs, save=False, now=NOW)
    assert [len(_names_in(c)) for c in calls] == [200, 200, 50]


def test_skill_false_stored_as_null(tree, monkeypatch):
    _fake_ask(monkeypatch, lambda n, i, kw: _answer([("python", "Python", True), ("dbt", "", False)]))
    _core(tree, save=False)
    assert json.loads(_aliases_path(tree).read_text())["dbt"] is None


def test_omitted_name_maps_to_itself_and_is_not_asked_again(tree, monkeypatch):
    _fake_ask(monkeypatch, lambda n, i, kw: _answer([]))
    _core(tree, save=False)
    assert json.loads(_aliases_path(tree).read_text()) == {"dbt": "dbt", "python": "Python"}
    calls = _fake_ask(monkeypatch, lambda *a: pytest.fail("no call expected"))
    _core(tree, save=False)
    assert calls == []


def test_answers_for_unsent_names_ignored(tree, monkeypatch):
    _fake_ask(monkeypatch, lambda n, i, kw: _answer([("python", "Python", True), ("dbt", "dbt", True), ("cobol", "COBOL", True)]))
    _core(tree, save=False)
    assert "cobol" not in json.loads(_aliases_path(tree).read_text())


def test_second_run_makes_no_call(tree, monkeypatch):
    calls = _fake_ask(monkeypatch, lambda n, i, kw: _answer([("python", "Python", True), ("dbt", "dbt", True)]))
    _core(tree, save=False)
    _core(tree, save=False)
    assert len(calls) == 1


def test_failed_call_still_reports_with_raw_names_and_warning(tree):
    r = _core(tree, save=False)
    assert r["warning"] and "not grouped" in r["warning"]
    assert {s["name"].lower() for s in r["skills"]} == {"python", "dbt"}
    assert not _aliases_path(tree).exists()


def test_bad_shape_sets_warning_keeps_earlier_chunks(tmp_path, monkeypatch):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile, {"role_targets": ["Data Engineer"], "min_score": 0.5})
    names = [f"skill{i:03d}" for i in range(250)]
    write_list_posting(jobs, "2026-10-20", "jobindex", "big", posted_at="2026-10-20T00:00:00+00:00", score=0.8,
                       score_reason="ok", scored_by="haiku", matching_skills=names)

    def handler(n, i, kw):
        return _answer([("skill000", "Skill Zero", True)]) if n == 1 else {"groups": "nope"}

    calls = _fake_ask(monkeypatch, handler)
    r = market_cmd._market_core(profile_dir=profile, jobs_dir=jobs, save=False, now=NOW)
    saved = json.loads((jobs / "skill_aliases.json").read_text())
    assert len(calls) == 2 and r["warning"]
    assert saved["skill000"] == "Skill Zero" and "skill001" in saved and "skill249" not in saved


def test_warning_key_always_present(tree):
    _write_aliases(tree, {"python": "Python", "dbt": "dbt"})
    r = _core(tree, save=False)
    assert "warning" in r and r["warning"] is None


def test_corrupt_alias_file_warns_no_call_not_overwritten(tree, monkeypatch):
    _aliases_path(tree).write_text("{not json", encoding="utf-8")
    calls = _fake_ask(monkeypatch, lambda *a: pytest.fail("no call expected"))
    r = _core(tree)
    assert calls == [] and r["warning"]
    assert _aliases_path(tree).read_text() == "{not json"
    _aliases_path(tree).write_text(json.dumps({"python": 3}), encoding="utf-8")
    assert _core(tree, save=False)["warning"]
    assert json.loads(_aliases_path(tree).read_text()) == {"python": 3}


def test_render_markdown_shows_warning_line(tree):
    text = market_cmd.render_markdown(_core(tree, save=False))
    assert "Warning:" in text


def test_hand_edit_wins_over_generated_on_merge(tree, monkeypatch):
    def handler(n, i, kw):
        _write_aliases(tree, {"dbt": "DBT (hand)"})  # edited while the call runs
        return _answer([("python", "Python", True), ("dbt", "dbt generated", True)])

    _fake_ask(monkeypatch, handler)
    _core(tree, save=False)
    saved = json.loads(_aliases_path(tree).read_text())
    assert saved["dbt"] == "DBT (hand)" and saved["python"] == "Python"


def test_alias_file_written_sorted_atomic(tree, monkeypatch):
    _fake_ask(monkeypatch, lambda n, i, kw: _answer([("python", "Python", True), ("dbt", "dbt", True)]))
    _core(tree, save=False)
    text = _aliases_path(tree).read_text()
    assert list(json.loads(text)) == sorted(json.loads(text))
    assert not list(tree[1].glob("skill_aliases.json.*.tmp"))


def test_no_save_still_merges_aliases_but_writes_no_report(tree, monkeypatch):
    _fake_ask(monkeypatch, lambda n, i, kw: _answer([]))
    _core(tree, save=False)
    assert _aliases_path(tree).exists() and not (tree[1] / "market").exists()


def test_lock_held_during_merge_uses_memory_aliases_with_warning(tree, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def held(jobs_dir, purpose):
        raise lock.LockHeldError("busy")
        yield

    _fake_ask(monkeypatch, lambda n, i, kw: _answer([("python", "Py Canon", True), ("dbt", "dbt", True)]))
    monkeypatch.setattr(lock, "ledger_lock", held)
    r = _core(tree)
    assert r["warning"] and "Py Canon" in {s["name"] for s in r["skills"]}
    assert not _aliases_path(tree).exists()


def test_ask_not_called_under_lock(tree, monkeypatch):
    from contextlib import contextmanager

    inside = []
    real = lock.ledger_lock
    state = {"in": False}

    @contextmanager
    def spy(jobs_dir, purpose):
        with real(jobs_dir, purpose):
            state["in"] = True
            try:
                yield
            finally:
                state["in"] = False

    monkeypatch.setattr(lock, "ledger_lock", spy)
    _fake_ask(monkeypatch, lambda n, i, kw: (inside.append(state["in"]), _answer([]))[1])
    _core(tree)
    assert inside == [False]
