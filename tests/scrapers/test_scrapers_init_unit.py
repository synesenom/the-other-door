"""Unit tests for scrapers/__init__.py helpers (unit layer).

Covers log_keyword_results: always reports a count event naming the keyword and
result count (never prints) — for both zero and non-zero lists, and `report`,
the scrapers' door to the progress channel (issue #202).
Also covers record_error/drain_errors (issue #132): the in-process error
accounting scrapers use to report a genuinely broken run (every request
failed) distinctly from a genuinely quiet one (no new postings, no errors).
Pure and offline — no network.
"""

import pytest

from door.core.progress import Progress
from door.scrapers import drain_errors, log_keyword_results, record_error, report, scrape_feeds, strip_html, tracked


@pytest.fixture(autouse=True)
def _clear_errors():
    """Drain any leftover state before and after each test for isolation."""
    drain_errors()
    yield
    drain_errors()


def test_log_keyword_results_reports_count_and_prints_nothing(progress_events, capsys):
    log_keyword_results("thehub", "data scientist", [{"id": "1"}])
    assert progress_events == [Progress("'data scientist': 1 results", site="thehub", stage="keyword")]
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_log_keyword_results_zero_results_reports_0_results(progress_events):
    log_keyword_results("lever", "analyst", [])
    assert [e.message for e in progress_events] == ["'analyst': 0 results"]


def test_report_forwards_to_core_channel_with_site_and_detail(progress_events):
    report("detail", 2, 5, site="thehub")
    assert progress_events == [Progress("detail", 2, 5, site="thehub")]


# --------------------------------------------------------------------------- #
# record_error / drain_errors (issue #132)
# --------------------------------------------------------------------------- #

def test_record_error_accumulates_multiple_messages_same_source():
    record_error("thehub", "error 1")
    record_error("thehub", "error 2")
    assert drain_errors() == {"thehub": ["error 1", "error 2"]}


def test_record_error_multiple_sources_kept_separate():
    record_error("thehub", "404 Not Found")
    record_error("teamtailor", "connection reset")
    drained = drain_errors()
    assert drained == {
        "thehub": ["404 Not Found"],
        "teamtailor": ["connection reset"],
    }


def test_drain_errors_clears_state():
    record_error("thehub", "boom")
    drain_errors()
    assert drain_errors() == {}


# --------------------------------------------------------------------------- #
# run_probe / probe_failure (issue #178)
# --------------------------------------------------------------------------- #

def _http_error(status):
    import requests

    resp = requests.Response()
    resp.status_code = status
    return requests.exceptions.HTTPError(f"{status}", response=resp)


def test_run_probe_ok_and_parse_failure():
    from door.scrapers import run_probe

    ok = run_probe(lambda: "raw", lambda raw: ([{"id": "1"}], True, ""), "json")
    assert ok == {"raw": "raw", "ext": "json", "postings": [{"id": "1"}], "structure_ok": True, "robots": "allowed"}

    def boom(raw):
        raise ValueError("bad json")

    bad = run_probe(lambda: "raw", boom, "json")
    assert bad["structure_ok"] is False and "bad json" in bad["reason"] and bad["raw"] == "raw"
    assert not bad.get("unreachable") and not bad.get("wall")


def test_run_probe_fetch_failures_are_wall_or_unreachable():
    import requests

    from door.scrapers import run_probe

    def failing(exc):
        def fetch():
            raise exc
        return run_probe(fetch, lambda raw: ([], True, ""), "html")

    assert failing(_http_error(403))["wall"] is True
    assert failing(_http_error(429))["wall"] is True
    assert failing(_http_error(500))["unreachable"] is True
    assert failing(requests.exceptions.ConnectionError("down"))["unreachable"] is True
    assert failing(requests.exceptions.ConnectionError("down"))["structure_ok"] is False


def test_parse_iso_date():
    from datetime import datetime, timezone

    from door.scrapers import parse_iso_date

    assert parse_iso_date("2026-01-02T03:04:05Z") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert parse_iso_date("2026-01-02") == datetime(2026, 1, 2)
    assert parse_iso_date("2026-06-12T14:01:16-04:00").utcoffset().total_seconds() == -4 * 3600
    for bad in (None, "", "yesterday", 123):
        assert parse_iso_date(bad) is None


def test_drain_errors_for_one_source_leaves_the_others():
    record_error("a", "boom")
    record_error("b", "bang")
    assert drain_errors("a") == {"a": ["boom"]}
    assert drain_errors("a") == {}
    assert drain_errors() == {"b": ["bang"]}


def test_record_error_is_safe_from_many_threads():
    import threading

    def spam(source):
        for i in range(200):
            record_error(source, str(i))

    threads = [threading.Thread(target=spam, args=(f"s{n}",)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    drained = drain_errors()
    assert sorted(drained) == [f"s{n}" for n in range(8)]
    assert all(len(v) == 200 for v in drained.values())


def test_tracked_yields_every_entry_and_reports_when_each_starts_and_ends(progress_events):
    seen = []
    for entry in tracked(["a", "b"]):
        seen.append(entry)
        assert progress_events[-1] == Progress(entry, stage="entry_start")
    assert seen == ["a", "b"]
    assert [(e.message, e.stage) for e in progress_events] == [
        ("a", "entry_start"), ("a", "entry_end"), ("b", "entry_start"), ("b", "entry_end"),
    ]


def test_tracked_ends_the_entry_a_break_left_open(progress_events):
    for entry in tracked(["a", "b"]):
        break
    assert [(e.message, e.stage) for e in progress_events][-1] == ("a", "entry_end")


def test_tracked_labels_entries_with_the_given_function(progress_events):
    list(tracked([{"id": 1}], label=lambda e: f"id{e['id']}"))
    assert progress_events[0].message == "id1"


# strip_html: the one HTML-to-text helper every scraper uses


def test_strip_html_keeps_one_line_per_block():
    assert strip_html("<p>Hi <b>there</b></p><p>Two &amp; three</p>") == "Hi there\nTwo & three"


def test_strip_html_breaks_lines_on_br_list_items_and_table_rows():
    assert strip_html("A<br />B<ul><li>x<li>y</ul><table><tr><td>r1</td></tr><tr><td>r2</td></tr></table>") == \
        "A\nB\nx\ny\nr1\nr2"


def test_strip_html_drops_comments_nbsp_and_invisible_characters():
    assert strip_html("<div><!--block-->A&nbsp;B\u200b\ufeff</div>") == "A B"


def test_strip_html_drops_blank_lines_and_collapses_spaces():
    assert strip_html("&nbsp;\nJob Function:&nbsp;Finance\n\n  x \t y  ") == "Job Function: Finance\nx y"


def test_strip_html_reads_entity_encoded_markup_when_told():
    """Greenhouse, Teamtailor and SuccessFactors send the markup itself entity-encoded."""
    assert strip_html("&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;p&gt;Bye&lt;/p&gt;", encoded=True) == \
        "Hello & welcome\nBye"


def test_strip_html_takes_none():
    assert strip_html(None) == ""


# scrape_feeds: the loop of every per-company feed


def _posting(pid, title="Engineer"):
    return {"platform_id": pid, "title": title}


def test_scrape_feeds_collects_each_entry_and_reports_its_count(progress_events):
    def fetch(session, entry, scraped_at):
        return [_posting(f"{entry}-1"), _posting(f"{entry}-2")]

    postings = scrape_feeds("acmeats", ["a", "b"], fetch)
    assert [p["platform_id"] for p in postings] == ["a-1", "a-2", "b-1", "b-2"]
    assert [(e.message, e.stage) for e in progress_events] == [
        ("a", "entry_start"), ("a", "entry_end"), ("b", "entry_start"), ("b", "entry_end"),
        ("'a': 2 results", "keyword"), ("'b': 2 results", "keyword"),
    ]


def test_scrape_feeds_records_a_failed_entry_and_goes_on():
    def fetch(session, entry, scraped_at):
        if entry == "bad":
            raise ValueError("boom")
        return [_posting("ok")]

    postings = scrape_feeds("acmeats", ["bad", "good"], fetch)
    assert [p["platform_id"] for p in postings] == ["ok"]
    assert drain_errors("acmeats") == {"acmeats": ["error fetching 'bad': boom"]}


def test_scrape_feeds_keeps_the_first_posting_of_each_key():
    def fetch(session, entry, scraped_at):
        return [_posting("same", title=entry), _posting(f"{entry}-own")]

    postings = scrape_feeds("acmeats", ["a", "b"], fetch)
    assert [p["platform_id"] for p in postings] == ["same", "a-own", "b-own"]
    assert postings[0]["title"] == "a"


def test_scrape_feeds_dedups_by_the_given_key():
    def fetch(session, entry, scraped_at):
        return [{"platform_id": "1", "url": f"https://{entry}/1"}]

    postings = scrape_feeds("acmeats", ["a", "b"], fetch, key=lambda p: p["url"])
    assert len(postings) == 2


def test_scrape_feeds_hands_every_entry_one_session_and_one_scrape_time():
    calls = []

    def fetch(session, entry, scraped_at):
        calls.append((session, scraped_at))
        return []

    scrape_feeds("acmeats", ["a", "b"], fetch, headers={"Accept": "application/json"})
    assert calls[0] == calls[1]
    assert calls[0][1].tzinfo is not None


def test_scrape_feeds_skips_a_posting_without_a_key():
    postings = scrape_feeds("acmeats", ["a"], lambda session, entry, at: [_posting(""), _posting("1")])
    assert [p["platform_id"] for p in postings] == ["1"]


def test_scrape_feeds_runs_hosts_side_by_side_and_keeps_entry_order():
    import threading
    import time

    threads = set()

    def fetch(session, entry, scraped_at):
        threads.add(threading.current_thread().name)
        time.sleep(0.05 if entry == "a.example" else 0)  # the first entry finishes last
        return [_posting("shared", title=entry), _posting(entry)]

    entries = ["a.example", "b.example", "c.example"]
    postings = scrape_feeds("acmeats", entries, fetch, group=lambda e: e, max_workers=3)
    assert [p["platform_id"] for p in postings] == ["shared", "a.example", "b.example", "c.example"]
    assert postings[0]["title"] == "a.example"
    assert len(threads) > 1


def test_scrape_feeds_records_a_failed_entry_when_run_side_by_side():
    def fetch(session, entry, scraped_at):
        if entry == "bad.example":
            raise ValueError("boom")
        return [_posting(entry)]

    postings = scrape_feeds("acmeats", ["bad.example", "ok.example"], fetch, group=lambda e: e, max_workers=2)
    assert [p["platform_id"] for p in postings] == ["ok.example"]
    assert drain_errors("acmeats") == {"acmeats": ["error fetching 'bad.example': boom"]}
