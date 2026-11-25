"""`core/page_fetch`: the one fetch tool of the page reader (#549), with its limits held by code."""

import asyncio

import pytest
import requests
import requests.adapters
import responses

from door.core import page_fetch
from door.scrapers import http_client

_REAL_SEND = requests.adapters.HTTPAdapter.send


@pytest.fixture
def fetcher(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    return page_fetch.PageFetcher(session=http_client.PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0, obey_robots=False))


@pytest.fixture
def real_network(monkeypatch):
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _REAL_SEND)


@responses.activate
def test_a_page_comes_back_as_its_text_and_its_links(fetcher):
    responses.add(responses.GET, "https://jane.example/", body=(
        '<html><head><style>p{}</style><script src="/app.js"></script></head><body><h1>Jane</h1><script>var x=1;</script>'
        '<p>Data scientist</p><a href="/research">Research</a><a href="https://github.com/jane">gh</a>'
        '<script>fetch("data/pubs.json")</script></body></html>'), content_type="text/html")
    text = fetcher.fetch("https://jane.example/")
    assert "Jane" in text and "Data scientist" in text
    assert "var x=1" not in text and "p{}" not in text
    for link in ("https://jane.example/research", "https://github.com/jane", "https://jane.example/app.js", "https://jane.example/data/pubs.json"):
        assert f"- {link}" in text


@responses.activate
def test_a_json_page_is_returned_as_it_is(fetcher):
    responses.add(responses.GET, "https://api.example/x", body='{"a": 1}', content_type="application/json")
    assert fetcher.fetch("https://api.example/x") == '{"a": 1}'


@responses.activate
def test_a_binary_page_is_refused(fetcher):
    responses.add(responses.GET, "https://jane.example/cv.pdf", body=b"%PDF", content_type="application/pdf")
    with pytest.raises(page_fetch.Refused):
        fetcher.fetch("https://jane.example/cv.pdf")


@responses.activate
def test_the_twenty_first_page_is_refused_without_a_request(fetcher):
    responses.add(responses.GET, "https://jane.example/p", body="x", content_type="text/plain")
    for _ in range(20):
        fetcher.fetch("https://jane.example/p")
    with pytest.raises(page_fetch.Refused) as err:
        fetcher.fetch("https://jane.example/p")
    assert "20" in str(err.value)
    assert len(responses.calls) == 20


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://192.168.1.10/admin", "http://169.254.169.254/latest/meta-data/", "http://localhost:8080/", "http://10.0.0.5/",
])
def test_a_private_address_is_refused(fetcher, real_network, url):
    with pytest.raises(page_fetch.Refused) as err:
        fetcher.fetch(url)
    assert "public" in str(err.value)


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/in/jane", "https://linkedin.com/in/jane", "https://dk.indeed.com/viewjob?jk=1", "https://uk.linkedin.com/x",
])
def test_linkedin_and_indeed_are_never_fetched(fetcher, url):
    with pytest.raises(page_fetch.Refused) as err:
        fetcher.fetch(url)
    assert "never fetched" in str(err.value)
    assert fetcher.fetched == 0  # a refusal for the site does not use up a page


@responses.activate
def test_a_redirect_to_linkedin_is_not_followed(fetcher):
    responses.add(responses.GET, "https://jane.example/in", status=302, headers={"Location": "https://www.linkedin.com/in/jane"})
    with pytest.raises(page_fetch.Refused):
        fetcher.fetch("https://jane.example/in")
    assert len(responses.calls) == 1


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/", "jane.example", "https://"])
def test_only_web_addresses_are_fetched(fetcher, url):
    with pytest.raises(page_fetch.Refused):
        fetcher.fetch(url)


@responses.activate
def test_a_page_that_fails_is_refused_with_the_reason(fetcher):
    responses.add(responses.GET, "https://jane.example/gone", status=404)
    with pytest.raises(page_fetch.Refused):
        fetcher.fetch("https://jane.example/gone")


@responses.activate
def test_a_long_page_is_cut(fetcher):
    responses.add(responses.GET, "https://jane.example/long", body="a" * (page_fetch.MAX_CHARS + 5000), content_type="text/plain")
    assert len(fetcher.fetch("https://jane.example/long")) <= page_fetch.MAX_CHARS + 100


def test_the_server_offers_only_fetch_page_and_answers_a_refusal_as_an_error():
    server = page_fetch.build_server(page_fetch.PageFetcher())
    assert [t.name for t in asyncio.run(server.list_tools())] == ["fetch_page"]
    with pytest.raises(Exception) as err:
        asyncio.run(server.call_tool("fetch_page", {"url": "https://www.linkedin.com/in/jane"}))
    assert "never fetched" in str(err.value)


def test_two_calls_at_once_cannot_pass_the_limit(monkeypatch):
    import threading
    import time

    class Slow:
        def get(self, url, **kwargs):
            time.sleep(0.01)  # a window for a count that is read and then written
            raise requests.ConnectionError("down")

    fetcher = page_fetch.PageFetcher(session=Slow())
    refused_for_limit = []

    def go():
        try:
            fetcher.fetch("https://jane.example/")
        except page_fetch.Refused as exc:
            if "limit" in str(exc):
                refused_for_limit.append(1)

    threads = [threading.Thread(target=go) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert fetcher.fetched == 20 and len(refused_for_limit) == 20
