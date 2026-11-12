"""Guard: robots.txt does not gate The other door's requests.

The bar is each site's terms: `http_client.OBEY_ROBOTS` is off. robots.txt is read
for its `Sitemap:` lines and `Crawl-delay`; the tests of the obeying behaviour use
the `obey_robots` fixture.
"""

from door.scrapers import http_client
from door.scrapers.http_client import PoliteSession


def test_robots_txt_does_not_gate_requests_by_default():
    assert http_client.OBEY_ROBOTS is False
    assert PoliteSession().obey_robots is False


def test_the_switch_is_read_when_a_session_is_made(monkeypatch):
    monkeypatch.setattr(http_client, "OBEY_ROBOTS", True)
    assert PoliteSession().obey_robots is True


def test_the_fetch_policy_is_pinned():
    """Changing either is a deliberate decision: see docs/job-sites.md, How The other door fetches."""
    ua = http_client.USER_AGENT
    assert http_client.OBEY_ROBOTS is False, "robots.txt does not gate requests; see docs/job-sites.md, How The other door fetches"
    assert ua.startswith("Mozilla/5.0 (") and "Chrome/" in ua, "the User-Agent is a common browser's; see docs/job-sites.md, How The other door fetches"
    assert "door" not in ua.lower() and "github" not in ua.lower(), "the User-Agent does not name The other door; see docs/job-sites.md, How The other door fetches"
    assert PoliteSession()._session.headers["User-Agent"] == ua
