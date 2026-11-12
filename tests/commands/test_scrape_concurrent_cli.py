"""`find`'s scrape stage runs the sites side by side (issue #254).

Scrapers produce in worker threads; the calling thread consumes and does every ledger,
history and file write. `scrape_workers: 1` is the old one-site-after-another run.
"""

import json
import threading

import pytest

from cli_utils import CaptureReporter
from door.commands import scrape as scrape_cmd
from profile_utils import write_config

_SITES = ["jobindex", "greenhouse", "lever"]


def _posting(site: str, n: int = 1) -> dict:
    return {
        "id": f"{site}-acme-data-scientist-{n}", "title": "Data Scientist", "company": "Acme",
        "location": "Copenhagen", "url": f"https://{site}.example/{n}", "source": site,
        "description": "We are looking for a data scientist who will join our team and work with Python.",
        "scraped_at": "2026-06-13T00:00:00Z", "platform_id": f"{site}-{n}",
    }


def _follow(profile_dir, platform, entry, name="Acme"):
    from door.core import companies

    items = companies.load(profile_dir)
    companies.record(items, name, feed=(platform, entry), status="followed", found_via="manual", reason=None)
    companies.save(profile_dir, items)


def _configure(env, workers, **extra):
    write_config(env.profile_dir, {
        "role_targets": ["data scientist"], "location": "Copenhagen", "scrape_workers": workers, **extra,
    })
    _follow(env.profile_dir, "greenhouse", "acme")
    _follow(env.profile_dir, "lever", "acme", name="Acme Lever")


def _fake(monkeypatch, site: str, scrape_fn):
    import importlib

    from door.core.sites import SITES

    module = importlib.import_module(SITES[site].module)
    monkeypatch.setattr(module, "scrape", scrape_fn)
    monkeypatch.delattr(module, "iter_scrape", raising=False)


def _run(env, sites=None, **kwargs):
    return scrape_cmd._scrape_core(sites or _SITES, jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kwargs)


def test_sites_are_in_flight_together_and_reported_in_config_order(cli_env, monkeypatch):
    _configure(cli_env, 8)
    barrier = threading.Barrier(3, timeout=5)  # passes only if all three sites run at once

    for site in _SITES:
        def scrape(config, site=site, **kwargs):
            barrier.wait()
            return [_posting(site)]
        _fake(monkeypatch, site, scrape)

    result = _run(cli_env)
    assert [(e["site"], e["outcome"], e["count"]) for e in result["sites"]] == [(s, "ok", 1) for s in _SITES]
    for site in _SITES:
        assert (cli_env.jobs_dir / "postings" / result["run_date"] / site / f"{site}-acme-data-scientist-1.json").exists()


def test_a_sites_errors_never_change_another_sites_outcome(cli_env, monkeypatch):
    from door.scrapers import record_error

    _configure(cli_env, 8)
    started = threading.Barrier(3, timeout=5)

    def broken(config, **kwargs):
        started.wait()
        record_error("jobindex", "404 Not Found")
        return []

    def quiet(config, **kwargs):
        started.wait()
        return []  # no errors, nothing at all: "empty"

    def fine(config, **kwargs):
        started.wait()
        return [_posting("lever")]

    _fake(monkeypatch, "jobindex", broken)
    _fake(monkeypatch, "greenhouse", quiet)
    _fake(monkeypatch, "lever", fine)

    by_site = {e["site"]: e for e in _run(cli_env)["sites"]}

    assert (by_site["jobindex"]["outcome"], by_site["jobindex"]["errors"]) == ("failed", ["404 Not Found"])
    assert (by_site["greenhouse"]["outcome"], by_site["greenhouse"]["errors"]) == ("empty", [])
    assert (by_site["lever"]["outcome"], by_site["lever"]["errors"]) == ("ok", [])


def test_one_worker_runs_the_sites_one_after_another_on_the_calling_thread(cli_env, monkeypatch):
    _configure(cli_env, 1)
    log, threads = [], set()

    for site in _SITES:
        def scrape(config, site=site, **kwargs):
            log.append(f"{site} start")
            threads.add(threading.current_thread())
            log.append(f"{site} end")
            return [_posting(site)]
        _fake(monkeypatch, site, scrape)

    result = _run(cli_env)

    assert log == [f"{s} {step}" for s in _SITES for step in ("start", "end")]
    assert threads == {threading.current_thread()}
    assert [e["count"] for e in result["sites"]] == [1, 1, 1]


def test_parallel_and_serial_runs_write_the_same_postings(tmp_path, cli_env, monkeypatch):
    for site in _SITES:
        _fake(monkeypatch, site, lambda config, site=site, **kw: [_posting(site, 1), _posting(site, 2)])

    outcomes = {}
    for workers in (1, 8):
        _configure(cli_env, workers)
        env = type(cli_env)(profile_dir=cli_env.profile_dir, jobs_dir=tmp_path / f"jobs{workers}")
        result = _run(env)
        files = sorted(p.relative_to(env.jobs_dir).as_posix() for p in env.jobs_dir.rglob("*.json")
                       if p.parent.parent.name == result["run_date"])
        history = json.loads((env.jobs_dir / "history.json").read_text())
        outcomes[workers] = ([(e["site"], e["outcome"], e["count"]) for e in result["sites"]], files, sorted(history))

    assert outcomes[1] == outcomes[8]


def test_progress_closes_each_site_with_a_running_count(cli_env, monkeypatch):
    _configure(cli_env, 8)
    for site in _SITES:
        _fake(monkeypatch, site, lambda config, site=site, **kw: [_posting(site)])
    cap = CaptureReporter()

    _run(cli_env, progress=cap)

    closing = [e for e in cap.events if e.outcome]
    assert sorted(e.site for e in closing) == sorted(_SITES)
    assert [(e.done, e.total) for e in closing] == [(1, 3), (2, 3), (3, 3)]
    starts = [e for e in cap.events if e.message.startswith("scraping (site")]
    assert sorted(e.message for e in starts) == [f"scraping (site {i}/3)" for i in (1, 2, 3)]


def test_events_inside_a_site_carry_that_sites_name(cli_env, monkeypatch):
    from door.scrapers import report

    _configure(cli_env, 8)
    meet = threading.Barrier(3, timeout=5)

    for site in _SITES:
        def scrape(config, site=site, **kwargs):
            meet.wait()
            report(f"hello from {site}")
            return [_posting(site)]
        _fake(monkeypatch, site, scrape)
    cap = CaptureReporter()

    _run(cli_env, progress=cap)

    assert {(e.message, e.site) for e in cap.events if e.message.startswith("hello")} == {
        (f"hello from {s}", s) for s in _SITES
    }


def test_a_streaming_site_still_writes_as_it_goes_and_honours_the_cap(cli_env, monkeypatch):
    import door.scrapers.boards.jobindex as ji

    _configure(cli_env, 8, max_postings_per_site=2)
    produced = []

    def iter_scrape(config, **kwargs):
        for n in range(1, 200):
            produced.append(n)
            yield _posting("jobindex", n)

    monkeypatch.setattr(ji, "iter_scrape", iter_scrape)
    _fake(monkeypatch, "greenhouse", lambda config, **kw: [_posting("greenhouse")])
    _fake(monkeypatch, "lever", lambda config, **kw: [_posting("lever")])

    result = _run(cli_env)
    entry = result["sites"][0]

    assert (entry["site"], entry["outcome"], entry["count"]) == ("jobindex", "ok", 2)
    assert len(produced) < 100  # the generator was stopped, not drained
    assert len(list((cli_env.jobs_dir / "postings" / result["run_date"] / "jobindex").glob("*.json"))) == 2


def test_a_scraper_that_raises_is_an_error_site_and_the_others_carry_on(cli_env, monkeypatch):
    _configure(cli_env, 8)

    def boom(config, **kwargs):
        raise RuntimeError("kaput")

    _fake(monkeypatch, "jobindex", boom)
    _fake(monkeypatch, "greenhouse", lambda config, **kw: [_posting("greenhouse")])
    _fake(monkeypatch, "lever", lambda config, **kw: [_posting("lever")])

    by_site = {e["site"]: e for e in _run(cli_env)["sites"]}

    assert by_site["jobindex"] == {"site": "jobindex", "outcome": "error", "error": "kaput"}
    assert by_site["greenhouse"]["outcome"] == by_site["lever"]["outcome"] == "ok"


def test_the_hub_runs_in_the_pool_like_every_other_board(cli_env, monkeypatch):
    _configure(cli_env, 8)
    seen = {}

    def scraper(site):
        def scrape(config, **kwargs):
            seen[site] = threading.current_thread()
            return [_posting(site)]
        return scrape

    _fake(monkeypatch, "jobindex", scraper("jobindex"))
    _fake(monkeypatch, "thehub", scraper("thehub"))

    result = _run(cli_env, ["jobindex", "thehub"])

    assert [e["outcome"] for e in result["sites"]] == ["ok", "ok"]
    assert seen["thehub"] is not threading.current_thread()
    assert seen["jobindex"] is not threading.current_thread()


def test_scrape_workers_must_be_at_least_one(cli_env):
    from door.core.profile_loader import ConfigError

    write_config(cli_env.profile_dir, {"scrape_workers": 0})
    with pytest.raises(ConfigError):
        _run(cli_env)


def test_a_site_reports_its_final_posting_count_before_it_closes(cli_env, monkeypatch):
    _configure(cli_env, 1)
    _fake(monkeypatch, "jobindex", lambda config, **kw: [_posting("jobindex", n) for n in (1, 2, 3)])
    cap = CaptureReporter()
    _run(cli_env, ["jobindex"], progress=cap)
    counts = [(e.done, e.site) for e in cap.events if e.stage == "postings"]
    assert counts[-1] == (3, "jobindex")
    assert [e.outcome for e in cap.events if e.stage == "scrape" and e.outcome] == ["ok"]
    assert cap.events.index(next(e for e in cap.events if e.stage == "postings" and e.done == 3)) < \
        cap.events.index(next(e for e in cap.events if e.outcome == "ok"))
