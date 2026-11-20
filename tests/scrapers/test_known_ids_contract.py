"""A scraper that skips a known id hands it back as a `seen_only` record (#436, behaviour of #434).

Each site is served from its saved fixture, scraped once for its ids, then again with those ids as
`known_ids`. The second run must account for every id of the first, by the same ledger id
(`make_job_id(site, platform_id)`): as a full posting (a scraper may ignore `known_ids`) or as
`{"platform_id", "seen_only": True}`; one that filters and returns nothing leaves the engine unable to
count the ad or refresh its `last_seen`. A `seen_only` id must cost no request the first run made for
that id's own page.

Covered: every single-employer feed served by `feeds/test_feed_names_contract.py`'s cases. Not covered
here (own multi-entry or listing fixtures, no one-entry serve helper): hr_manager, career_sites, oracle_hcm.
Boards: each with its own serve helpers (`_BOARDS`; Workable, also a board, is a feed above). A scraper that serves its whole answer
from one listing and ignores `known_ids` (no detail request to save) passes by returning full postings."""

import importlib
import importlib.util
import sys

import pytest
import responses

from door.core import models
from door.core.sites import SITES
from paths import TESTS_DIR

_HERE = TESTS_DIR / "scrapers"


def _load(path, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


_NAMES = _load(_HERE / "feeds" / "test_feed_names_contract.py", "_known_ids_names_contract")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _requested():
    return [c.request.url for c in responses.calls]


def _check(site, run):
    """`run(known_ids)` serves the fixture and scrapes it; the contract over its two answers."""
    first = run(frozenset())
    assert first, f"{site}: the fixture scrape gave nothing"
    urls_first = _requested()
    by_pid = {p["platform_id"]: p["id"] for p in first}
    assert all(models.make_job_id(site, pid) == jid for pid, jid in by_pid.items())
    responses.reset()

    second = run(frozenset(by_pid))
    urls_second = _requested()

    ledger = {site_id: pid for pid, site_id in by_pid.items()}
    seen = {models.make_job_id(site, r["platform_id"]) for r in second if r.get("seen_only")}
    full = {r["id"] for r in second if not r.get("seen_only")}
    assert seen | full == set(ledger), f"{site}: known ids dropped: {sorted(set(ledger) - seen - full)}"
    seen = {ledger[i] for i in seen}
    assert all(set(r) == {"platform_id", "seen_only"} and r["seen_only"] is True for r in second if r.get("seen_only"))
    for pid in seen:
        assert not [u for u in urls_second if pid in u], f"{site}: a request for the known id {pid}"
    return seen


def _feed_run(site):
    def run(known_ids):
        stem, serve, entry, _ = _NAMES._CASES[site]
        serve(_NAMES._helpers(stem))
        config = {SITES[site].config_key: [entry]}
        return importlib.import_module(SITES[site].module).scrape(config, known_ids=known_ids)
    return run


@pytest.mark.parametrize("site", sorted(_NAMES._CASES))
@responses.activate
def test_a_feed_hands_known_ids_back_as_seen_only(site):
    _check(site, _feed_run(site))


# --- boards: how each serves its saved fixture, from the helpers of its scrape test -------------

def _board(name):
    return _load(_HERE / "boards" / f"test_{name}_scrape.py", f"_known_ids_board_{name}")


def _scrape_board(site, config, known_ids):
    return importlib.import_module(SITES[site].module).scrape(config, known_ids=known_ids)


def _arbetsformedlingen(monkeypatch):
    m = _board("arbetsformedlingen")
    monkeypatch.setattr(m.af, "_PAGE_SIZE", 4)
    return lambda k: (m._serve_pages(), _scrape_board("arbetsformedlingen", m._CFG, k))[1]


def _choisirleservicepublic():
    m = _board("choisirleservicepublic")
    return lambda k: (m._serve_search(), m._serve_details(m._ALL), _scrape_board("choisirleservicepublic", m._CFG, k))[2]


def _euraxess(monkeypatch):
    m = _board("euraxess")
    monkeypatch.setattr(m.euraxess.time, "sleep", lambda *a, **k: None)
    return lambda k: (m._mock_pages(), _scrape_board("euraxess", m._CFG, k))[1]


def _francetravail():
    m = _board("francetravail")
    return lambda k: (m._serve_search(), m._serve_details(m._ALL), _scrape_board("francetravail", m._CFG, k))[2]


def _globalnyt():
    m = _board("globalnyt")
    return lambda k: (m._serve(), _scrape_board("globalnyt", m._CFG, k))[1]


def _jobbank():
    m = _board("jobbank")
    return lambda k: (m._serve_search(), m._serve_details(m._PAGE1 + m._PAGE2 + m._PAGE3),
                      _scrape_board("jobbank", m._CFG, k))[2]


def _jobindex():
    m = _board("jobindex")
    config = {"role_targets": ["data scientist", "domain architect"], "location": "Copenhagen"}
    html = "text/html; charset=utf-8"

    def run(k):
        responses.add(responses.GET, m._SEARCH, body=m._fx("search_page1.html"), content_type=html)
        responses.add(responses.GET, m._SEARCH, body=m._fx("search_empty.html"), content_type=html)
        for tid in ("h1673146", "h1673246"):
            responses.add(responses.GET, m.jobindex._DETAIL_URL.format(tid=tid), body=m._fx(f"detail_{tid}.html"),
                          content_type=html)
        return _scrape_board("jobindex", config, k)
    return run


def _jobmaskinen():
    m = _board("jobmaskinen")

    def run(k):
        m._search("elektriker", 1, "search_page1.html")
        m._serve(m.jobmaskinen._search_url("elektriker", 2), m._fx("search_last_page.html"))
        for job_id in ("6535434", "6535427"):
            m._detail(job_id)
        for job_id in ("6535450", "6530742", "6529404"):
            m._detail(job_id, "detail_6535434.html")
        return _scrape_board("jobmaskinen", m._CFG, k)
    return run


def _jobs_ac_uk(monkeypatch):
    m = _board("jobs_ac_uk")
    monkeypatch.setattr(m.jobs_ac_uk, "_today", lambda: m.date(2026, 11, 3))
    return lambda k: (m._serve_search(), m._serve_details(m._PAGE1 + m._PAGE2), _scrape_board("jobs_ac_uk", m._CFG, k))[2]


def _kozigallas(monkeypatch):
    m = _board("kozigallas")
    monkeypatch.setattr(m.kozigallas, "_PAGE_SIZE", 3)
    return lambda k: (m._serve_list(), m._serve_details(m._ALL), _scrape_board("kozigallas", m._CFG, k))[2]


def _nhs_jobs():
    m = _board("nhs_jobs")
    return lambda k: (m._serve_search(), m._serve_details(m._PAGE1 + m._PAGE2),
                      _scrape_board("nhs_jobs", {**m._CFG, "max_pages_per_keyword": 2}, k))[2]


def _reed():
    m = _board("reed")
    return lambda k: (m._serve_search(), m._serve_details(m._PAGE1 + m._PAGE2), _scrape_board("reed", m._CFG, k))[2]


def _reliefweb():
    m = _board("reliefweb")
    return lambda k: (m._serve(), _scrape_board("reliefweb", m._ANY, k))[1]


def _thehub():
    m = _board("thehub")

    def run(k):
        m._serve(m.thehub._listing_url("data scientist", "DK", 1), m._listing(m._fx("listing_page1.json")))
        m._serve(m.thehub._listing_url("data scientist", "DK", 2), m._listing(m._fx("listing_page2.json")))
        m._serve(m.thehub._job_url("6aa1f3cc961a30471ccb36b8"), m._detail(m._fx("detail_flatpay.json")))
        m._serve(m.thehub._job_url("6a918622eb2ed4dae7b2f5fa"), m._detail({}))
        m._serve(m.thehub._job_url(m._LUNAR), m._detail(m._fx("detail_lunar.json")))
        return _scrape_board("thehub", m._CFG, k)
    return run


_BOARDS = {f.__name__.lstrip("_"): f for f in (
    _arbetsformedlingen, _choisirleservicepublic, _euraxess, _francetravail, _globalnyt, _jobbank, _jobindex,
    _jobmaskinen, _jobs_ac_uk, _kozigallas, _nhs_jobs, _reed, _reliefweb, _thehub)}


def test_every_board_is_checked():
    assert set(_BOARDS) == {name for name, site in SITES.items() if site.board and not site.config_key}


def _board_run(site, monkeypatch):
    make = _BOARDS[site]
    return make(monkeypatch) if make.__code__.co_argcount else make()


@pytest.mark.parametrize("site", sorted(_BOARDS))
@responses.activate
def test_a_board_hands_known_ids_back_as_seen_only(site, monkeypatch):
    _check(site, _board_run(site, monkeypatch))


@pytest.mark.parametrize("site, make_run", [("dayforce", lambda s, mp: _feed_run(s)),
                                            ("jobbank", _board_run)])
@responses.activate
def test_a_scraper_that_drops_known_ids_fails_the_contract(site, make_run, monkeypatch):
    """The test of the test: a scraper whose known ids are filtered out with no record returned is caught."""
    run = make_run(site, monkeypatch)
    module = importlib.import_module(SITES[site].module)
    real = module.scrape
    monkeypatch.setattr(module, "scrape", lambda config, known_ids=frozenset(), **kw: [
        p for p in real(config, known_ids=known_ids, **kw) if not p.get("seen_only")])

    with pytest.raises(AssertionError, match="known ids dropped"):
        _check(site, run)
