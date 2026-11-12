"""Unit tests for scrapers/http_client.py — PoliteSession.

All tests are offline; network calls are mocked with `responses` or
monkeypatched. The module under test is scrapers.http_client.
"""


import pytest
import requests
import responses

from door.scrapers import http_client
from door.scrapers.http_client import PoliteSession, RobotsBlocked

# These tests fetch robots.txt for real (from `responses`), not the allow-all stub.
pytestmark = [pytest.mark.real_robots, pytest.mark.usefixtures("obey_robots")]

_JOB_URL = "https://example.com/jobs/123"
_ROBOTS_URL = "https://example.com/robots.txt"


# ---------------------------------------------------------------------------
# Jitter delay
# ---------------------------------------------------------------------------


@responses.activate
def test_jitter_delay_within_range(monkeypatch):
    """Sleep is called once with a value within [min_delay, max_delay]."""
    sleeps = []
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: sleeps.append(s))

    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\n", content_type="text/plain")
    responses.add(responses.GET, _JOB_URL, body="OK", status=200)

    session = PoliteSession(min_delay=0.5, max_delay=1.5)
    session.get(_JOB_URL, check_robots=False)

    assert len(sleeps) == 1
    assert 0.5 <= sleeps[0] <= 1.5


# ---------------------------------------------------------------------------
# 429 backoff
# ---------------------------------------------------------------------------


@responses.activate
def test_429_triggers_backoff_and_retries(monkeypatch):
    """On two 429 responses followed by 200, the call succeeds and backoff sleeps grow."""
    sleeps = []
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: sleeps.append(s))

    # Two 429 then 200
    responses.add(responses.GET, _JOB_URL, status=429)
    responses.add(responses.GET, _JOB_URL, status=429)
    responses.add(responses.GET, _JOB_URL, body="OK", status=200)

    session = PoliteSession(min_delay=0.0, max_delay=0.0, max_retries=3)
    resp = session.get(_JOB_URL, check_robots=False)
    assert resp.status_code == 200

    # At least 3 sleeps: one inter-request delay + two backoff waits
    assert len(sleeps) >= 3
    # The two backoff sleeps (indices 1 and 2 in sleeps after the first normal sleep)
    # should be positive and the second backoff >= the first backoff
    backoff_sleeps = sleeps[1:]  # skip the initial inter-request delay
    assert all(s > 0 for s in backoff_sleeps)
    assert backoff_sleeps[1] >= backoff_sleeps[0]


# ---------------------------------------------------------------------------
# 5xx backoff
# ---------------------------------------------------------------------------


@responses.activate
def test_5xx_triggers_backoff_and_retries(monkeypatch):
    """On two 503 responses followed by 200, the call succeeds."""
    sleeps = []
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: sleeps.append(s))

    responses.add(responses.GET, _JOB_URL, status=503)
    responses.add(responses.GET, _JOB_URL, status=503)
    responses.add(responses.GET, _JOB_URL, body="OK", status=200)

    session = PoliteSession(min_delay=0.0, max_delay=0.0, max_retries=3)
    resp = session.get(_JOB_URL, check_robots=False)
    assert resp.status_code == 200
    # At least one backoff sleep happened
    assert len(sleeps) >= 2


# ---------------------------------------------------------------------------
# Non-retryable 4xx
# ---------------------------------------------------------------------------


@responses.activate
def test_non_retryable_4xx_raised_immediately(monkeypatch):
    """403 is not retried — HTTPError raised after exactly one attempt."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    responses.add(responses.GET, _JOB_URL, status=403)

    session = PoliteSession(min_delay=0.0, max_delay=0.0, max_retries=3)
    with pytest.raises(Exception):
        session.get(_JOB_URL, check_robots=False)

    # Only one call was made
    assert len(responses.calls) == 1


# ---------------------------------------------------------------------------
# Max retries exhausted
# ---------------------------------------------------------------------------


@responses.activate
def test_max_retries_exhausted_raises(monkeypatch):
    """After max_retries 429 responses, HTTPError is re-raised."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    # Four 429s — more than max_retries=3
    for _ in range(4):
        responses.add(responses.GET, _JOB_URL, status=429)

    session = PoliteSession(min_delay=0.0, max_delay=0.0, max_retries=3)
    with pytest.raises(Exception):
        session.get(_JOB_URL, check_robots=False)


# ---------------------------------------------------------------------------
# robots.txt — disallowed
# ---------------------------------------------------------------------------


@responses.activate
def test_robots_disallows_url_raises(monkeypatch):
    """When robots.txt disallows the URL, RobotsBlocked is raised before the GET."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    responses.add(
        responses.GET,
        _ROBOTS_URL,
        body="User-agent: *\nDisallow: /\n",
        content_type="text/plain",
    )
    # The job URL should NOT be fetched
    responses.add(responses.GET, _JOB_URL, body="OK", status=200)

    session = PoliteSession(min_delay=0.0, max_delay=0.0)
    with pytest.raises(RobotsBlocked):
        session.get(_JOB_URL, check_robots=True)

    # Only robots.txt was fetched, not the job URL
    called_urls = [c.request.url for c in responses.calls]
    assert _ROBOTS_URL in called_urls
    assert not any(_JOB_URL == u for u in called_urls)


# ---------------------------------------------------------------------------
# robots.txt — allowed
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# check_robots=False skips robots fetch
# ---------------------------------------------------------------------------


@responses.activate
def test_robots_check_disabled_skips_robots_fetch(monkeypatch):
    """When check_robots=False, no robots.txt fetch is made."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    responses.add(responses.GET, _JOB_URL, body="OK", status=200)

    session = PoliteSession(min_delay=0.0, max_delay=0.0)
    resp = session.get(_JOB_URL, check_robots=False)
    assert resp.status_code == 200

    # Only one HTTP call — the job URL
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == _JOB_URL


# ---------------------------------------------------------------------------
# robots.txt cache — per domain
# ---------------------------------------------------------------------------


@responses.activate
def test_robots_cached_per_domain(monkeypatch):
    """robots.txt is fetched exactly once per origin across multiple requests."""
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: None)

    responses.add(
        responses.GET,
        _ROBOTS_URL,
        body="User-agent: *\nDisallow: /admin/\n",
        content_type="text/plain",
    )
    responses.add(responses.GET, "https://example.com/jobs/123", body="OK", status=200)
    responses.add(responses.GET, "https://example.com/jobs/456", body="OK", status=200)

    session = PoliteSession(min_delay=0.0, max_delay=0.0)
    session.get("https://example.com/jobs/123", check_robots=True)
    session.get("https://example.com/jobs/456", check_robots=True)

    # robots.txt fetched only once
    robots_calls = [c for c in responses.calls if "/robots.txt" in c.request.url]
    assert len(robots_calls) == 1


# ---------------------------------------------------------------------------
# Retry-After header
# ---------------------------------------------------------------------------


@responses.activate
def test_retry_after_header_respected(monkeypatch):
    """When 429 contains Retry-After: 5, backoff sleep is >= 5."""
    sleeps = []
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: sleeps.append(s))

    responses.add(
        responses.GET,
        _JOB_URL,
        status=429,
        headers={"Retry-After": "5"},
    )
    responses.add(responses.GET, _JOB_URL, body="OK", status=200)

    session = PoliteSession(min_delay=0.0, max_delay=0.0, max_retries=3)
    resp = session.get(_JOB_URL, check_robots=False)
    assert resp.status_code == 200

    # The backoff sleep (after the initial inter-request sleep) should be >= 5
    backoff_sleeps = [s for s in sleeps if s >= 5]
    assert len(backoff_sleeps) >= 1
    assert backoff_sleeps[0] >= 5


# ---------------------------------------------------------------------------
# Issue #226: User-Agent, RFC 9309 robots, Crawl-delay, redirects
# ---------------------------------------------------------------------------

@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: sleeps.append(s))
    return sleeps


# ---------------------------------------------------------------------------
# robots.txt off (OBEY_ROBOTS = False, the default)
# ---------------------------------------------------------------------------


@responses.activate
def test_a_url_robots_disallows_is_fetched_when_robots_is_not_obeyed(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nDisallow: /\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0, max_delay=0, obey_robots=False)
    assert session.get(_JOB_URL).text == "OK"
    assert session.allows(_JOB_URL)
    session.ensure_allowed(_JOB_URL)


@responses.activate
def test_an_unreachable_robots_txt_blocks_nothing_when_robots_is_not_obeyed(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, status=503)
    responses.add(responses.GET, _JOB_URL, body="OK")
    assert PoliteSession(min_delay=0, max_delay=0, obey_robots=False).get(_JOB_URL).text == "OK"


@responses.activate
def test_crawl_delay_is_honoured_and_sitemaps_read_though_robots_does_not_gate(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL,
                  body="User-agent: *\nDisallow: /\nCrawl-delay: 3\nSitemap: https://example.com/jobs.xml\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0.1, max_delay=0.2, obey_robots=False)
    assert session.get(_JOB_URL).text == "OK"  # disallowed, fetched anyway
    assert no_sleep == [3.0]
    assert session.sitemaps(_JOB_URL) == ("https://example.com/jobs.xml",)


@responses.activate
def test_a_shorter_crawl_delay_does_not_shorten_the_pause_when_robots_is_not_obeyed(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nCrawl-delay: 0.01\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    PoliteSession(min_delay=0.1, max_delay=0.2, obey_robots=False).get(_JOB_URL)
    assert 0.1 <= no_sleep[0] <= 0.2


@responses.activate
def test_an_unreachable_robots_txt_adds_no_crawl_delay(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, status=503)
    responses.add(responses.GET, _JOB_URL, body="OK")
    PoliteSession(min_delay=0.1, max_delay=0.2, obey_robots=False).get(_JOB_URL)
    assert 0.1 <= no_sleep[0] <= 0.2


# ---------------------------------------------------------------------------
# robots.txt obeyed (OBEY_ROBOTS = True)
# ---------------------------------------------------------------------------


@responses.activate
def test_robots_txt_is_fetched_with_the_sessions_user_agent(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    PoliteSession(min_delay=0, max_delay=0).get(_JOB_URL)
    assert responses.calls[0].request.headers["User-Agent"] == http_client.USER_AGENT


@responses.activate
def test_wildcard_rules_are_honoured(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nDisallow: /*page=\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0, max_delay=0)
    assert session.get(_JOB_URL).text == "OK"
    with pytest.raises(RobotsBlocked):
        session.get(_JOB_URL + "?page=2")


@responses.activate
def test_crawl_delay_is_respected_when_longer_than_the_jitter(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\nCrawl-delay: 3\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    PoliteSession(min_delay=0.1, max_delay=0.2).get(_JOB_URL)
    assert no_sleep == [3.0]


@responses.activate
def test_a_missing_robots_txt_allows_everything(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, status=404)
    responses.add(responses.GET, _JOB_URL, body="OK")
    assert PoliteSession(min_delay=0, max_delay=0).get(_JOB_URL).text == "OK"


@responses.activate
def test_a_robots_txt_server_error_blocks_the_host(no_sleep):
    """RFC 9309: an unreachable robots.txt means complete disallow."""
    responses.add(responses.GET, _ROBOTS_URL, status=503)
    responses.add(responses.GET, _JOB_URL, body="OK")
    with pytest.raises(RobotsBlocked):
        PoliteSession(min_delay=0, max_delay=0).get(_JOB_URL)


@responses.activate
def test_a_rate_limited_robots_txt_blocks_the_host(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, status=429)
    with pytest.raises(RobotsBlocked):
        PoliteSession(min_delay=0, max_delay=0).get(_JOB_URL)


@responses.activate
def test_an_unreachable_robots_txt_blocks_the_host(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body=requests.exceptions.ConnectionError("down"))
    with pytest.raises(RobotsBlocked):
        PoliteSession(min_delay=0, max_delay=0).get(_JOB_URL)


@responses.activate
def test_each_redirect_hop_is_checked_against_its_own_robots(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\n")
    responses.add(responses.GET, _JOB_URL, status=302, headers={"Location": "https://ats.example.org/ad/1"})
    responses.add(responses.GET, "https://ats.example.org/robots.txt", body="User-agent: *\nDisallow: /\n")
    with pytest.raises(RobotsBlocked) as exc:
        PoliteSession(min_delay=0, max_delay=0).get(_JOB_URL)
    assert exc.value.url == "https://ats.example.org/ad/1"
    assert not any(c.request.url == "https://ats.example.org/ad/1" for c in responses.calls)


@responses.activate
def test_an_allowed_redirect_is_followed_and_its_url_kept(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\n")
    responses.add(responses.GET, _JOB_URL, status=301, headers={"Location": "/jobs/124"})
    responses.add(responses.GET, "https://example.com/jobs/124", body="moved here")
    resp = PoliteSession(min_delay=0, max_delay=0).get(_JOB_URL)
    assert resp.text == "moved here"
    assert resp.url == "https://example.com/jobs/124"


@responses.activate
def test_ensure_allowed_checks_without_fetching(no_sleep):
    """The browser scrapers ask before `page.goto`."""
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nDisallow: /jobs/\n")
    session = PoliteSession(min_delay=0, max_delay=0)
    with pytest.raises(RobotsBlocked):
        session.ensure_allowed(_JOB_URL)
    session.ensure_allowed("https://example.com/about")
    assert [c.request.url for c in responses.calls] == [_ROBOTS_URL]


# ---------------------------------------------------------------------------
# Issue #254: pacing is per host, so only requests to different hosts overlap
# ---------------------------------------------------------------------------

import threading  # noqa: E402
import time as _real_time  # noqa: E402

_REAL_SLEEP = _real_time.sleep


def _host_url(host: str, n: int = 1) -> str:
    return f"https://{host}/jobs/{n}"


@responses.activate
def test_two_threads_on_one_host_alternate_pause_and_request(monkeypatch):
    """Threads sharing a host still queue: every request is preceded by its own pause."""
    log, log_lock = [], threading.Lock()

    def sleep(seconds):
        with log_lock:
            log.append("pause")
        _REAL_SLEEP(0.005)  # give the other thread every chance to barge in

    def page(request):
        with log_lock:
            log.append("request")
        return 200, {}, "OK"

    monkeypatch.setattr("door.scrapers.http_client.time.sleep", sleep)
    responses.add_callback(responses.GET, _host_url("a.example", 1), callback=page)
    responses.add_callback(responses.GET, _host_url("a.example", 2), callback=page)
    session = PoliteSession(min_delay=0.5, max_delay=0.5)

    threads = [threading.Thread(target=lambda n=n: [session.get(_host_url("a.example", n), check_robots=False) for _ in range(3)])
               for n in (1, 2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert log == ["pause", "request"] * 6


@responses.activate
def test_a_pause_on_one_host_does_not_hold_up_another_host(monkeypatch):
    """Host B's request completes while host A's thread is still inside its pause."""
    b_done = threading.Event()
    a_saw_b_done = []

    def sleep(seconds):
        if threading.current_thread().name == "host-a":
            a_saw_b_done.append(b_done.wait(timeout=3))

    def host_b(request):
        b_done.set()
        return 200, {}, "OK"

    monkeypatch.setattr("door.scrapers.http_client.time.sleep", sleep)
    responses.add(responses.GET, _host_url("a.example"), body="OK")
    responses.add_callback(responses.GET, _host_url("b.example"), callback=host_b)
    session = PoliteSession(min_delay=1.0, max_delay=1.0)

    a = threading.Thread(target=lambda: session.get(_host_url("a.example"), check_robots=False), name="host-a")
    a.start()
    session.get(_host_url("b.example"), check_robots=False)
    a.join()

    assert a_saw_b_done == [True]


@responses.activate
def test_crawl_delay_of_one_host_does_not_slow_another(monkeypatch):
    pauses = {}

    def sleep(seconds):
        pauses[threading.current_thread().name] = seconds

    monkeypatch.setattr("door.scrapers.http_client.time.sleep", sleep)
    responses.add(responses.GET, "https://slow.example/robots.txt", body="User-agent: *\nCrawl-delay: 7\n")
    responses.add(responses.GET, "https://quick.example/robots.txt", body="User-agent: *\nAllow: /\n")
    responses.add(responses.GET, _host_url("slow.example"), body="OK")
    responses.add(responses.GET, _host_url("quick.example"), body="OK")
    session = PoliteSession(min_delay=1.0, max_delay=2.0)

    threads = [threading.Thread(target=session.get, args=(_host_url(h),), name=h) for h in ("slow.example", "quick.example")]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert pauses["slow.example"] == 7.0
    assert 1.0 <= pauses["quick.example"] <= 2.0


@responses.activate
def test_robots_txt_is_fetched_once_per_host_across_threads(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda s: _REAL_SLEEP(0.002))
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0, max_delay=0)

    threads = [threading.Thread(target=session.get, args=(_JOB_URL,)) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert [c.request.url for c in responses.calls].count(_ROBOTS_URL) == 1


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------


@responses.activate
def test_post_sends_json_after_the_same_pause_and_checks_robots(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\n")
    responses.add(responses.POST, "https://example.com/api", json={"ok": True})
    resp = PoliteSession(min_delay=1, max_delay=2).post("https://example.com/api", json={"q": 1})
    assert resp.json() == {"ok": True}
    assert responses.calls[-1].request.body == b'{"q": 1}'
    assert 1 <= no_sleep[-1] <= 2


@responses.activate
def test_post_is_blocked_by_robots_by_default(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nDisallow: /\n")
    responses.add(responses.POST, "https://example.com/api", json={})
    with pytest.raises(RobotsBlocked):
        PoliteSession(min_delay=0, max_delay=0).post("https://example.com/api", json={})


@responses.activate
def test_redirect_target_reads_the_location_without_following_it(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\n")
    responses.add(responses.GET, "https://example.com/s/abc", status=302, headers={"Location": "/real/page?x=1"})
    session = PoliteSession(min_delay=0, max_delay=0)
    assert session.redirect_target("https://example.com/s/abc") == "https://example.com/real/page?x=1"
    assert [c.request.url for c in responses.calls if "robots" not in c.request.url] == ["https://example.com/s/abc"]


@responses.activate
def test_redirect_target_is_none_when_the_page_does_not_redirect(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nAllow: /\n")
    responses.add(responses.GET, "https://example.com/plain", body="hi")
    assert PoliteSession(min_delay=0, max_delay=0).redirect_target("https://example.com/plain") is None


def test_employer_feeds_share_one_short_pause():
    """One constant for the feed scrapers' pause, not a literal in each of them."""
    import re

    from paths import PACKAGE_DIR

    assert http_client.FEED_DELAY == (0.2, 0.5)
    feeds = ("ashby", "greenhouse", "lever", "recruitee", "pinpoint", "teamtailor", "successfactors",
             "hr_manager", "workable", "career_sites")
    paced = r"min_delay=FEED_DELAY\[0\], max_delay=FEED_DELAY\[1\], timeout=30"
    assert re.search(paced, (PACKAGE_DIR / "scrapers" / "__init__.py").read_text(encoding="utf-8"))  # scrape_feeds
    for name in feeds:
        text = (PACKAGE_DIR / "scrapers" / "feeds" / f"{name}.py").read_text(encoding="utf-8")
        assert "min_delay=1.0" not in text and "max_delay=2.0" not in text, name
        assert re.search(paced, text) or "scrape_feeds(" in text, name


# ---------------------------------------------------------------------------
# Issue #545: no single wait, and no employer, can hold a run
# ---------------------------------------------------------------------------


@responses.activate
def test_a_crawl_delay_of_an_hour_is_paced_at_the_cap(no_sleep):
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nCrawl-delay: 3600\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0.1, max_delay=0.2, obey_robots=False)
    assert session.get(_JOB_URL).text == "OK"
    assert no_sleep == [http_client.MAX_PAUSE_S]
    assert http_client.MAX_PAUSE_S <= 60


@responses.activate
def test_a_huge_retry_after_is_capped(no_sleep):
    responses.add(responses.GET, _JOB_URL, status=429, headers={"Retry-After": "86400"})
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0.0, max_delay=0.0, max_retries=2)
    assert session.get(_JOB_URL, check_robots=False).status_code == 200
    assert max(no_sleep) <= http_client.MAX_PAUSE_S


@responses.activate
def test_a_retry_after_date_far_ahead_is_capped(no_sleep):
    responses.add(responses.GET, _JOB_URL, status=503, headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"})
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0.0, max_delay=0.0, max_retries=2)
    session.get(_JOB_URL, check_robots=False)
    assert max(no_sleep) <= http_client.MAX_PAUSE_S


@responses.activate
def test_a_request_past_the_threads_budget_is_not_made(no_sleep, monkeypatch):
    """Under `budget(...)` a request that has no time left raises instead of waiting its pause."""
    clock = [1000.0]
    monkeypatch.setattr("door.scrapers.http_client.time.monotonic", lambda: clock[0])
    responses.add(responses.GET, _ROBOTS_URL, body="User-agent: *\nCrawl-delay: 20\n")
    responses.add(responses.GET, _JOB_URL, body="OK")
    session = PoliteSession(min_delay=0.1, max_delay=0.2, obey_robots=False)
    with http_client.budget(30) as spent:
        assert session.get(_JOB_URL).text == "OK"          # 20 s pause fits
        clock[0] += 25                                      # 5 s left, the next pause is 20 s
        with pytest.raises(http_client.BudgetExceeded):
            session.get(_JOB_URL)
        assert spent.hit
    assert no_sleep == [20.0]
    # outside the block nothing is bounded again
    assert session.get(_JOB_URL).text == "OK"


def test_budget_is_per_thread():
    import threading

    seen = []
    with http_client.budget(5):
        t = threading.Thread(target=lambda: seen.append(http_client.current_deadline()))
        t.start()
        t.join()
    assert seen == [None]


# ---------------------------------------------------------------------------
# A total deadline per request (#599)
# ---------------------------------------------------------------------------


@pytest.fixture
def trickle_server():
    """A real local server that sends its headers, then one byte every 0.1 s for 6 s."""
    import socket
    import threading
    import time

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    stop = threading.Event()

    def serve():
        conn, _ = srv.accept()
        try:
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
            end = time.monotonic() + 6
            while time.monotonic() < end and not stop.is_set():
                conn.sendall(b"x")
                time.sleep(0.1)
        except OSError:
            pass
        finally:
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}/"
    stop.set()
    srv.close()


@pytest.fixture
def real_network(monkeypatch):
    import requests.adapters

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _REAL_SEND)


import requests.adapters as _adapters  # noqa: E402

_REAL_SEND = _adapters.HTTPAdapter.send


def test_a_server_trickling_bytes_hits_the_total_deadline(trickle_server, real_network):
    import time

    session = PoliteSession(min_delay=0, max_delay=0, timeout=5, total_timeout=1, max_retries=0, obey_robots=False)
    start = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout):
        session.get(trickle_server, check_robots=False)
    assert time.monotonic() - start < 3


def test_a_trickling_robots_txt_is_cut_at_the_threads_budget(trickle_server, real_network):
    import time

    session = PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0, obey_robots=False)
    start = time.monotonic()
    with http_client.budget(1) as spent:
        with pytest.raises(http_client.BudgetExceeded):
            session.get(trickle_server)
    assert spent.hit
    assert time.monotonic() - start < 3


# ---------------------------------------------------------------------------
# system_trust: verify against the OS trust store
# ---------------------------------------------------------------------------


def test_system_trust_mounts_the_truststore_adapter():
    """With system_trust, a host's session verifies through truststore; by default it does not."""
    session = PoliteSession(system_trust=True)
    adapter = session._session_for("example.com").get_adapter("https://example.com/")
    assert isinstance(adapter, http_client.SystemTrustAdapter)


def test_default_session_keeps_the_stock_adapter():
    session = PoliteSession()
    adapter = session._session_for("example.com").get_adapter("https://example.com/")
    assert not isinstance(adapter, http_client.SystemTrustAdapter)


def test_system_trust_adapter_builds_a_verifying_truststore_context():
    import ssl

    ctx = http_client.SystemTrustAdapter()._context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert type(ctx).__module__.startswith("truststore")
