"""Every scraper's session comes from `http_client` (`PoliteSession` or `public_session`): a plain
`requests.Session()` would reach private addresses and read the system proxy."""
import re

from tests.paths import REPO_ROOT

SCRAPERS = REPO_ROOT / "src" / "door" / "scrapers"


def test_no_scraper_opens_a_plain_requests_session():
    plain = re.compile(r"requests\.Session\(\)|from requests import [^\n]*\bSession\b")
    found = [
        f"{path.relative_to(REPO_ROOT)}:{n}"
        for path in SCRAPERS.rglob("*.py") if path.name != "http_client.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if plain.search(line)
    ]
    assert found == []
