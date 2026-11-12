"""Unit tests for scripts/country_smoke.py: the live whole-country run, judged by pure functions.

The live run itself (real boards, LinkedIn, `claude -p`) is opt-in and not part of the suite; here the judges, the
report, the sandbox state helpers and the driver's wiring (with `_find_core` faked) are checked offline.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from door.commands import _common as common
from door.commands import find as find_cmd
from door.core import companies, lock, workspace
from door.matching import scorer
from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("country_smoke", REPO_ROOT / "scripts" / "country_smoke.py")
cs = importlib.util.module_from_spec(_spec)
sys.modules["country_smoke"] = cs
_spec.loader.exec_module(cs)

sys.path.insert(0, str(REPO_ROOT / "tests" / "pipeline"))
from test_pipeline_countries_end_to_end import COUNTRIES  # noqa: E402


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    for module, name in [(workspace, "PROFILE_DIR"), (workspace, "JOBS_DIR"), (lock, "pre_acquire_hook"),
                         (lock, "post_release_hook"), (scorer, "score_postings"), (common, "_claude_available")]:
        monkeypatch.setattr(module, name, getattr(module, name))


def _statuses(lines):
    return [line.status for line in lines]


# --- the table -------------------------------------------------------------------------------------------------

def test_profile_rows_match_offline_e2e_countries():
    assert set(COUNTRIES) <= set(cs.PROFILES)
    for name, row in cs.PROFILES.items():
        if name in COUNTRIES:
            assert row["languages"] == COUNTRIES[name]["languages"]
            assert row["location"] == COUNTRIES[name]["location"]
        assert row["cc"] and row["keywords"] and row["floor"] >= 0.5


def test_profession_rows_are_the_suites_professions():
    from professions import PROFESSIONS

    extras = {n: r for n, r in cs.PROFILES.items() if n not in COUNTRIES}
    assert set(extras) == {f"dk-{p}" for p in PROFESSIONS}
    for name, row in extras.items():
        config = PROFESSIONS[row["profession"]]["config"]
        assert name == f"dk-{row['profession']}" and row["cc"] == "dk" and row["location"] == "Copenhagen, Denmark"
        assert row["languages"] == config["languages"] and row["local_language"] == "da"
        assert row["keywords"] == config["search_keywords"]
        assert row["role_targets"] == config["role_targets"] and row["topic_terms"] == config["topic_terms"]


def test_write_config_writes_a_professions_targets_and_topic_terms(tmp_path):
    from profile_utils import write_config

    write_config(tmp_path, {})
    cs.write_config(tmp_path, cs.PROFILES["dk-nurse"], discovery=False)
    config = json.loads((tmp_path / "config.json").read_text())
    row = cs.PROFILES["dk-nurse"]
    assert config["role_targets"] == row["role_targets"] and config["topic_terms"] == row["topic_terms"]
    assert config["search_keywords"] == row["keywords"]


# --- judges ----------------------------------------------------------------------------------------------------

def test_judge_search_one_line_per_board():
    block = {"sites": [
        {"site": "a", "outcome": "ok", "count": 5},
        {"site": "b", "outcome": "ok", "count": 0},
        {"site": "c", "outcome": "failed", "count": 0, "errors": ["boom"]},
        {"site": "d", "outcome": "empty", "count": 0, "warning": "nothing at all"},
        {"site": "e", "outcome": "resting", "until": "2026-10-29T10:00"},
        {"site": "f", "outcome": "not_configured"},
    ]}
    lines = cs.judge_search(block)
    assert [l.name for l in lines] == list("abcdef")
    assert _statuses(lines) == [cs.PASS, cs.FAIL, cs.FAIL, cs.FAIL, cs.SITE_SIDE, cs.SKIP]
    assert "boom" in lines[2].detail and "nothing at all" in lines[3].detail and "2026-10-29" in lines[4].detail


def test_judge_discover():
    base = {"queued": 0, "skipped": None, "outcome": "ok"}
    assert _statuses(cs.judge_discover({**base, "queued": 3})) == [cs.PASS]
    assert _statuses(cs.judge_discover({**base, "outcome": "refused"})) == [cs.SITE_SIDE]
    assert _statuses(cs.judge_discover({**base, "outcome": None, "skipped": "LinkedIn resting until 10:00"})) == [cs.SITE_SIDE]
    assert _statuses(cs.judge_discover({**base, "outcome": None, "skipped": "linkedin_discovery is off"})) == [cs.FAIL]
    assert _statuses(cs.judge_discover(base)) == [cs.FAIL]
    assert _statuses(cs.judge_discover(None)) == [cs.SKIP]


def test_judge_follow_reports_counts_and_unresolved_names():
    block = {"followed": [{"company": "A"}], "unfollowable": [],
             "unresolved": [{"company": "B", "reason": "no feed"}, {"company": "C", "reason": "none"},
                            {"company": "D", "reason": "x"}]}
    (line,) = cs.judge_follow(block)
    assert line.status == cs.PASS
    assert "1 followed" in line.detail and "3 unresolved" in line.detail
    assert "B (no feed)" in line.detail and "C (none)" in line.detail and "D" not in line.detail


def test_local_share():
    search = {"sites": [{"site": "a", "outcome": "ok", "count": 5, "non_local": 1}]}
    collect = {"postings": 3, "non_local": 1}
    assert cs.local_share(search, collect) == pytest.approx(8 / 10)
    assert cs.local_share({"sites": []}, {"postings": 0, "non_local": 0}) is None
    assert cs.local_share(None, None) is None


def test_judge_collect():
    ok = {"postings": 4, "failed": 0}
    assert _statuses(cs.judge_collect(ok, [], 0.9, 0.5)) == [cs.SKIP]
    assert _statuses(cs.judge_collect({"postings": 0, "failed": 0}, ["A"], None, 0.5)) == [cs.FAIL]
    lines = cs.judge_collect({"postings": 0, "failed": 2}, ["A"], None, 0.5)
    assert lines[0].status == cs.FAIL and "2" in lines[0].detail
    lines = cs.judge_collect(ok, ["A"], 0.4, 0.5)
    assert _statuses(lines) == [cs.PASS, cs.FAIL] and "0.40" in lines[1].detail and "0.50" in lines[1].detail
    assert _statuses(cs.judge_collect(ok, ["A"], 0.5, 0.5)) == [cs.PASS, cs.PASS]


def test_judge_match():
    block = {"scored": 5, "failed": [], "passes": {"language": {"languages": {"en": 6, "de": 2}, "dropped": 2}}}
    assert _statuses(cs.judge_match(block, ["English"])) == [cs.PASS]
    assert "stubbed" in cs.judge_match(block, ["English"], stubbed=True)[0].detail
    assert _statuses(cs.judge_match({**block, "scored": 0}, ["English"])) == [cs.FAIL]
    assert _statuses(cs.judge_match({**block, "failed": ["x"]}, ["English"])) == [cs.FAIL]
    no_en = {**block, "passes": {"language": {"languages": {"de": 2}, "dropped": 2}}}
    assert _statuses(cs.judge_match(no_en, ["English"])) == [cs.FAIL]
    local = {**block, "passes": {"language": {"languages": {"en": 3, "hu": 4}, "dropped": 3}}}
    assert _statuses(cs.judge_match(local, ["English", "Hungarian"])) == [cs.FAIL]  # 3 of 4 hu ads dropped
    kept = {**block, "passes": {"language": {"languages": {"en": 3, "hu": 4}, "dropped": 0}}}
    assert _statuses(cs.judge_match(kept, ["English", "Hungarian"])) == [cs.PASS]


# --- report ----------------------------------------------------------------------------------------------------

def test_render_markdown_verdict_and_exit_code(tmp_path):
    lines = [cs.Line("search", "a", cs.PASS, "5"), cs.Line("search", "b", cs.SITE_SIDE, "resting")]
    text = cs.render_markdown("dk-en", "2026-10-28", lines)
    assert text.startswith("# Country smoke: dk-en (2026-10-28)")
    assert "| search | a | PASS | 5 |" in text and "| search | b | SITE-SIDE | resting |" in text
    assert text.rstrip().endswith("Verdict: PASS")
    assert cs.exit_code(lines) == 0
    bad = lines + [cs.Line("match", "m", cs.FAIL, "none")]
    assert cs.verdict(bad) == cs.FAIL and cs.exit_code(bad) == 1
    assert cs.exit_code([cs.Line("x", "y", cs.SKIP, "")]) == 0
    assert cs.report_path(tmp_path, "dk", "2026-10-28") == tmp_path / "dk" / "smoke-2026-10-28.md"


# --- sandbox state ---------------------------------------------------------------------------------------------

def test_seed_pace_keeps_pushback(tmp_path):
    (tmp_path / "discovery").mkdir()
    (tmp_path / "discovery" / "linkedin.json").write_text(json.dumps({"pushback_at": "2026-10-28T01:00:00+00:00"}))
    cs.seed_discover_pace(tmp_path, 10)
    state = json.loads((tmp_path / "discovery" / "linkedin.json").read_text())
    assert state["pushback_at"] == "2026-10-28T01:00:00+00:00" and state["pace"]["budget"] == 10


def test_carry_over_keeps_only_the_rests(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    (old / "jobs" / "discovery").mkdir(parents=True)
    (new / "jobs").mkdir(parents=True)
    cs.carry_over(old, new)  # nothing to copy
    assert not (new / "jobs" / "scrape_state.json").exists()
    (old / "jobs" / "scrape_state.json").write_text(json.dumps({
        "jobindex": {"last_success": "2026-10-30T00:00:00"},
        "thehub": {"last_success": "2026-10-30T00:00:00", "pushback_at": "2026-10-30T01:00:00"}}))
    (old / "jobs" / "discovery" / "linkedin.json").write_text(json.dumps(
        {"last_run": "x", "seen": {"a": 1}, "pushback_at": "2026-10-30T02:00:00", "pace": {"budget": 10}}))
    cs.carry_over(old, new)
    state = json.loads((new / "jobs" / "scrape_state.json").read_text())
    assert state == {"thehub": {"pushback_at": "2026-10-30T01:00:00"}}  # no watermark: the board is read whole
    li = json.loads((new / "jobs" / "discovery" / "linkedin.json").read_text())
    assert li == {"pushback_at": "2026-10-30T02:00:00"}


def test_fresh_sandbox_starts_from_nothing(tmp_path, monkeypatch):
    path = tmp_path / "sb"
    (path / "jobs" / "postings").mkdir(parents=True)
    (path / "jobs" / "postings" / "old.json").write_text("{}")
    (path / "jobs" / "history.json").write_text("{}")
    (path / "jobs" / "scrape_state.json").write_text(json.dumps({"jobindex": {"last_success": "x"}}))
    monkeypatch.setattr(cs.sandbox, "install", lambda p: (Path(p) / "jobs").mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(cs, "write_config", lambda *a, **k: None)
    cs.fresh_sandbox(path, {}, discovery=True)
    assert not (path / "jobs" / "postings").exists()
    assert not (path / "jobs" / "history.json").exists()
    assert not (path / "jobs" / "scrape_state.json").exists()


def test_clear_report_removes_the_days_file(tmp_path):
    report = cs.report_path(tmp_path, "dk", "2026-10-31")
    report.parent.mkdir(parents=True)
    report.write_text("stale")
    cs.clear_report(tmp_path, "dk", "2026-10-31")
    assert not report.exists()
    cs.clear_report(tmp_path, "dk", "2026-10-31")  # none: fine


# --- driver ----------------------------------------------------------------------------------------------------

def _block(step, **extra):
    base = {
        "search": {"sites": [{"site": "jobindex", "outcome": "ok", "count": 5, "non_local": 0}]},
        "discover": {"queued": 2, "skipped": None, "outcome": "ok"},
        "follow": {"followed": [], "unfollowable": [], "unresolved": []},
        "collect": {"postings": 3, "failed": 0, "non_local": 0},
        "match": {"scored": 2, "failed": [], "passes": {"language": {"languages": {"en": 3}, "dropped": 0}}},
    }[step]
    return {**base, **extra}


@pytest.fixture
def fake_core(monkeypatch):
    calls = []
    followed = ["Acme", "Globex", "Initech", "Umbrella"]
    overrides = {}

    def fake(step=None, **kw):
        calls.append((step, kw))
        if step == "follow" and not kw.get("dry_run"):
            items = [companies.Company(name=n, feed=companies.Feed(platform="greenhouse", id=n.lower()),
                                       status="followed", found_via="manual") for n in followed]
            companies.save(workspace.PROFILE_DIR, items)
        return {step: overrides.get(step, _block(step))}

    monkeypatch.setattr(find_cmd, "_find_core", fake)
    fake.calls, fake.followed, fake.overrides = calls, followed, overrides
    return fake


def _run(tmp_path, argv):
    return cs.main([*argv, "--dir", str(tmp_path)])


def test_run_row_order_and_collect_cap(tmp_path, fake_core):
    assert _run(tmp_path, ["dk", "--langs", "en", "--collect", "2"]) == 0
    steps = [(s, kw.get("dry_run", False)) for s, kw in fake_core.calls]
    assert steps == [("search", False), ("discover", False), ("follow", True), ("follow", False),
                     ("collect", False), ("match", False)]
    collect = [kw for s, kw in fake_core.calls if s == "collect"][0]
    assert collect["companies"] == ["Acme", "Globex"]
    assert list((tmp_path / "dk").glob("smoke-*.md"))
    assert (tmp_path / "dk" / "smoke-sandbox-dk-en").is_dir()


def test_profession_runs_only_its_row(tmp_path, fake_core):
    assert _run(tmp_path, ["dk", "--profession", "nurse"]) == 0
    assert [s for s, _ in fake_core.calls].count("search") == 1
    assert (tmp_path / "dk" / "smoke-sandbox-dk-nurse").is_dir()
    assert not (tmp_path / "dk" / "smoke-sandbox-dk-en").exists()
    assert not (tmp_path / "dk" / "smoke-sandbox-dk-electrician").exists()
    cfg = json.loads((tmp_path / "dk" / "smoke-sandbox-dk-nurse" / "profile" / "config.json").read_text())
    assert cfg["role_targets"] == cs.PROFILES["dk-nurse"]["role_targets"]


def test_unknown_profession(tmp_path, capsys):
    assert _run(tmp_path, ["dk", "--profession", "astronaut"]) == 2
    assert "nurse" in capsys.readouterr().err


def test_nothing_followed_skips_collect(tmp_path, fake_core):
    fake_core.followed.clear()
    assert _run(tmp_path, ["dk", "--langs", "en"]) == 0
    assert "collect" not in [s for s, _ in fake_core.calls]
    assert "nothing followed" in next(tmp_path.glob("dk/smoke-*.md")).read_text()


def test_both_languages_search_once_and_copy_jobs(tmp_path, fake_core):
    assert _run(tmp_path, ["hu", "--langs", "both"]) == 0
    steps = [s for s, _ in fake_core.calls]
    assert steps.count("search") == 1 and steps.count("discover") == 1 and steps.count("match") == 2
    assert (tmp_path / "hu" / "smoke-sandbox-hu-en").is_dir() and (tmp_path / "hu" / "smoke-sandbox-hu-en-hu").is_dir()
    cfg = json.loads((tmp_path / "hu" / "smoke-sandbox-hu-en-hu" / "profile" / "config.json").read_text())
    assert cfg["languages"] == ["English", "Hungarian"] and cfg["linkedin_discovery"] is False
    assert cfg["profession_discovery"] is False and cfg["jobbsafari_discovery"] is False
    common._load_config(tmp_path / "hu" / "smoke-sandbox-hu-en" / "profile")  # every key is declared in Profile


def test_failing_search_exits_1(tmp_path, fake_core):
    fake_core.overrides["search"] = {"sites": [{"site": "jobindex", "outcome": "failed", "count": 0, "errors": ["x"]}]}
    assert _run(tmp_path, ["dk", "--langs", "en"]) == 1


def test_step_exception_is_a_fail_line(tmp_path, monkeypatch, fake_core):
    def boom(step=None, **kw):
        if step == "discover":
            raise RuntimeError("kaput")
        return fake_core(step, **kw)

    monkeypatch.setattr(find_cmd, "_find_core", boom)
    assert _run(tmp_path, ["dk", "--langs", "en"]) == 1
    assert "kaput" in next(tmp_path.glob("dk/smoke-*.md")).read_text()


def test_local_language_unsupported_is_skipped(tmp_path, fake_core):
    assert _run(tmp_path, ["dk", "--langs", "local"]) == 0
    assert "no supported local language" in next(tmp_path.glob("dk/smoke-*.md")).read_text()
    assert fake_core.calls == []


def test_unknown_country(tmp_path, capsys):
    assert _run(tmp_path, ["zz"]) == 2
    assert "dk" in capsys.readouterr().err


def test_stub_scoring_patches_the_scorer(tmp_path, monkeypatch, fake_core):
    seen = {}

    def spy(step=None, **kw):
        if step == "match":
            seen["score"] = scorer.score_postings
            seen["claude"] = common._claude_available()
        return fake_core(step, **kw)

    real = scorer.score_postings
    monkeypatch.setattr(find_cmd, "_find_core", spy)
    assert _run(tmp_path, ["dk", "--langs", "en", "--stub-scoring"]) == 0
    assert seen["claude"] is True and seen["score"] is not real
    assert "stubbed" in next(tmp_path.glob("dk/smoke-*.md")).read_text()


def test_judge_discover_reports_each_source():
    block = {"queued": 257, "skipped": None, "outcome": "ok", "sources": {
        "linkedin": {"queued": 50, "skipped": None, "outcome": "ok"},
        "hellowork": {"queued": 0, "skipped": "hellowork_discovery is off", "outcome": None},
        "jobbsafari": {"queued": 0, "skipped": "resting until 10:00", "outcome": None},
        "profession": {"queued": 0, "skipped": "not for se", "outcome": None},
    }}
    lines = cs.judge_discover(block)
    by = {l.name: l for l in lines}
    assert set(by) == {"linkedin", "hellowork", "jobbsafari"}  # a source that does not serve the country is not a line
    assert by["linkedin"].status == cs.PASS and "50 employers" in by["linkedin"].detail
    assert by["hellowork"].status == cs.FAIL and by["jobbsafari"].status == cs.SITE_SIDE


def test_cap_queue_keeps_n_spread_over_sources(tmp_path):
    from door.core import candidates
    queue = {f"a{i}": {"name": f"a{i}", "sources": ["linkedin"]} for i in range(10)}
    queue.update({f"b{i}": {"name": f"b{i}", "sources": ["jobindex"]} for i in range(10)})
    candidates.save(tmp_path, queue)
    assert cs.cap_queue(tmp_path, 6) == 20
    kept = candidates.load(tmp_path)
    assert len(kept) == 6
    assert sum(k.startswith("a") for k in kept) == 3
    assert cs.cap_queue(tmp_path, 0) == 6  # 0 = no cap: nothing trimmed, the count before
    assert len(candidates.load(tmp_path)) == 6


def test_second_sandbox_does_not_inherit_run_records(tmp_path, monkeypatch):
    src = tmp_path / "src"
    (src / "jobs" / "runs").mkdir(parents=True)
    (src / "jobs" / "runs" / "latest.log").write_text("x")
    (src / "jobs" / "postings").mkdir()
    dst = tmp_path / "dst"
    (dst / "jobs").mkdir(parents=True)
    cs.copy_jobs(src, dst)
    assert (dst / "jobs" / "postings").is_dir() and not (dst / "jobs" / "runs").exists()


def test_collect_skips_the_example_profiles_manual_employers(tmp_path, monkeypatch):
    """The sandbox starts from profile.example, whose followed employers are Danish and `manual`: collect must
    read the employers this run's follow found, or it never touches a feed of the country under test. An
    employer queued only by a source `found_via` does not name (HelloWork, France Travail) is recorded as
    `manual` too, so what counts is that this run's follow added it."""
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path)
    feed = lambda n: companies.Feed(platform="lever", id=n.lower())  # noqa: E731
    example = [companies.Company(name=n, feed=feed(n), status="followed", found_via="manual")
               for n in ("Region Hovedstaden", "Københavns Kommune", "Pleo")]
    companies.save(tmp_path, example)
    before = cs._known_names()
    found = [companies.Company(name="Pigment", feed=feed("pigment"), status="followed", found_via="linkedin"),
             companies.Company(name="Quandela", feed=None, status="unresolved", found_via="linkedin"),
             companies.Company(name="Skeepers", feed=feed("skeepers"), status="followed", found_via="linkedin"),
             companies.Company(name="Doctolib", feed=feed("doctolib"), status="followed", found_via="manual")]
    companies.save(tmp_path, example + found)

    assert cs._followed_names(2, before) == ["Pigment", "Skeepers"]
    assert cs._followed_names(10, before) == ["Pigment", "Skeepers", "Doctolib"]


def test_judge_match_names_why_postings_failed_to_score():
    block = {"scored": 5, "failed": ["a", "b"], "passes": {},
             "failures": [{"id": "a", "error": "claude exited 1: overloaded"}, {"id": "b", "error": "claude exited 1: overloaded"}]}
    line = cs.judge_match(block, ["English"])[0]
    assert line.status == cs.FAIL and "2 postings failed to score (claude exited 1: overloaded)" in line.detail
    # a record from before the reasons were kept still reads
    assert "(" not in cs.judge_match({**block, "failures": None}, ["English"])[0].detail.split("score")[1]


# --- a step that never returns (#599) ----------------------------------------------------------------------------

@pytest.fixture
def stuck(monkeypatch, fake_core):
    """`follow` (the one named in `which`: dry or real) saves what it has and then never returns."""
    import threading

    release = threading.Event()
    real = fake_core

    def make(which):
        def fake(step=None, **kw):
            if step == "follow" and bool(kw.get("dry_run")) == (which == "dry"):
                if which == "real":
                    real(step, **kw)  # records the employers it has done
                release.wait(30)
                return {step: {}}
            return real(step, **kw)

        monkeypatch.setattr(find_cmd, "_find_core", fake)

    yield make
    release.set()


def test_a_follow_that_never_returns_is_a_site_side_line_and_the_report_is_written(tmp_path, stuck, fake_core):
    stuck("real")
    assert _run(tmp_path, ["dk", "--langs", "en", "--step-timeout", "0.3"]) == 0
    text = next(tmp_path.glob("dk/smoke-*.md")).read_text()
    assert "SITE-SIDE" in text and "stopped after 0 s, 4 employers done" in text
    assert "FAIL" not in text
    assert "collect" in text and "still running" in text  # skipped, not failed


def test_a_dry_run_that_never_returns_is_site_side_too(tmp_path, stuck, fake_core):
    stuck("dry")
    assert _run(tmp_path, ["dk", "--langs", "en", "--step-timeout", "0.3"]) == 0
    text = next(tmp_path.glob("dk/smoke-*.md")).read_text()
    assert "dry run stopped after 0 s" in text
    assert "FAIL" not in text
