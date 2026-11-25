"""The page reader's one tool (#549): `fetch_page(url)`, served over MCP by `python -m door.core.page_fetch`.

The call that reads a user's public pages (`core/page_reader`) sees no private data, so this is all it can
do, and its limits are held here, in code, not by the prompt: at most `MAX_PAGES` pages per server process
(one process per `claude -p` call), only public addresses and a size cap (`PoliteSession`, #548), robots.txt
obeyed, and LinkedIn and Indeed never fetched (their terms), not even as the target of a redirect.
"""

import re
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from door.scrapers import http_client

MAX_PAGES = 20
MAX_CHARS = 40_000   # of one page's text, links apart
MAX_LINKS = 150
NO_FETCH_NAMES = ("linkedin", "indeed")   # a label of the host, any subdomain or country

# A data file a script-rendered page names in its source (.json, .bib).
_DATA_FILE = re.compile(r"""["']([^"'\s<>]+\.(?:json|bib))["']""")


class Refused(Exception):
    """A page that is not fetched; the message is what the model reads."""


def is_no_fetch(host: str) -> bool:
    """Whether *host* is a site whose terms forbid fetching it (LinkedIn, Indeed)."""
    return any(label in NO_FETCH_NAMES for label in host.lower().split("."))


def _check_target(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Refused(f"{url} is not a web address (http or https)")
    if is_no_fetch(parts.hostname):
        raise Refused(f"{parts.hostname} is never fetched (its terms forbid it); skip it")


def _html_text(html: str, base: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    links = [urljoin(base, a["href"]) for a in soup.find_all("a", href=True)]
    links += [urljoin(base, s["src"]) for s in soup.find_all("script", src=True)]
    links += [urljoin(base, m) for m in _DATA_FILE.findall(html)]
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    lines = (" ".join(line.split()) for line in soup.get_text("\n").splitlines())
    text = "\n".join(line for line in lines if line)[:MAX_CHARS]
    kept = [link for link in dict.fromkeys(links) if link.startswith(("http://", "https://"))][:MAX_LINKS]
    return text + ("\n\nLinks:\n" + "\n".join(f"- {link}" for link in kept) if kept else "")


class PageFetcher:
    """Fetches pages for one reader call, counting them."""

    def __init__(self, session: http_client.PoliteSession | None = None, max_pages: int = MAX_PAGES) -> None:
        self.session = session or http_client.PoliteSession(min_delay=0.5, max_delay=1.0, timeout=15, max_retries=1)
        self.max_pages = max_pages
        self.fetched = 0

    def fetch(self, url: str) -> str:
        """The page at *url* as text with its links; `Refused` (with the reason) when it is not fetched."""
        url = url.strip()
        _check_target(url)
        if self.fetched >= self.max_pages:
            raise Refused(f"the limit of {self.max_pages} pages is used up; answer with what you have read")
        self.fetched += 1
        try:
            resp = self.session.get(url, before_redirect=_check_target)
        except Refused:
            raise
        except http_client.NotPublicAddress:
            raise Refused(f"{urlsplit(url).hostname} is not a public internet address; it is not fetched") from None
        except http_client.RobotsBlocked:
            raise Refused(f"{url} is closed to automatic readers (robots.txt)") from None
        except requests.RequestException as exc:
            raise Refused(f"could not fetch {url}: {type(exc).__name__}") from None
        kind = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if kind in ("", "text/html", "application/xhtml+xml"):
            return _html_text(resp.text, resp.url)
        if kind.startswith("text/") or kind.endswith(("json", "xml")) or kind in ("application/x-bibtex",):
            return resp.text[:MAX_CHARS]
        raise Refused(f"{url} is {kind or 'not text'}, not a page of text")


def build_server(fetcher: PageFetcher) -> MCPServer:
    """An MCP server with the one tool."""
    server = MCPServer("pages", log_level="WARNING")

    @server.tool()
    def fetch_page(url: str) -> str:
        """Fetch one public web page and return its text and its links (at most 20 pages per run; never LinkedIn or Indeed)."""
        try:
            return fetcher.fetch(url)
        except Refused as exc:
            raise ToolError(str(exc)) from None

    return server


def main() -> None:
    build_server(PageFetcher()).run(transport="stdio")


if __name__ == "__main__":
    main()
