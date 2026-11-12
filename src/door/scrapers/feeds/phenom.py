"""Phenom (issue #282, #438): a front end for another job system, usually Workday, so it has no `Site` of its own.

A career host that is a CNAME for Phenom's is named, and `resolve` looks through it: the host's search-results page
(its locale is read from where the home page redirects to, else from the sitemap) and one job page carry the apply
link of the system behind it. That system is followed only when its public job list is not empty
(`sdk.follow_link`: a Workday site's own job list or sitemap); otherwise the employer stays unfollowable with
``refusal="cant_yet"``, since many Phenom customers' Workday sites list nothing publicly.

`LINK_PLATFORMS` is empty when a link to it on a page must not decide which platform the page is on."""

import re
from urllib.parse import urlparse

import requests

from door.scrapers.sdk import Detection, RobotsBlocked, unfollowable
from door.scrapers.sdk import follow_link as _follow_link  # (not `follow_link`: that name is a platform hook)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("phenompeople.net", "phenompeople.com")

_REASON = "Phenom: a front end for another system (usually Workday); not followed"
_URL = re.compile(r"""https?://[^\s"'<>\\)]+""")
_LOCALE_PATH = re.compile(r"^/([^/]+/[^/]+)(?:/|$)")
_MAX_LINKS = 5  # apply links tried per employer, each a different site


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for Phenom's."""
    return unfollowable("phenom", where, _REASON, "cant_yet") if target.endswith(".phenompeople.net") else None


def _get(session, url: str):
    """The page at *url*, or None when it cannot be read."""
    try:
        return session.get(url, headers={"Accept": "text/html,application/xml"})
    except (requests.RequestException, RobotsBlocked):
        return None


def _locale(session, host: str, home) -> str | None:
    """``/global/en``: the region and language the host's pages live under, from where the home page redirected to
    (``/global/en/home``), a search-results link on it, or the first sitemap URL."""
    final = urlparse(home.url).path if home is not None else ""
    match = _LOCALE_PATH.match(final)
    if match:
        return "/" + match.group(1)
    link = re.search(rf"https?://{re.escape(host)}(/[^/\"'\s]+/[^/\"'\s]+)/search-results", home.text) if home is not None else None
    if link:
        return link.group(1)
    sitemap = _get(session, f"https://{host}/sitemap.xml")
    found = re.search(rf"<loc>https?://{re.escape(host)}(/[^/<]+/[^/<]+)", sitemap.text) if sitemap is not None else None
    return found.group(1) if found else None


def _links(text: str) -> list[str]:
    return list(dict.fromkeys(m.rstrip(".,;") for m in _URL.findall(text)))


def resolve(session, det: Detection, url: str) -> Detection:
    """*det* (a Phenom career host, *url* a link on it) looked through to the system behind it: that system's
    detection when its public job list is not empty, else *det* with the reason (no link found, or the list
    empty). *det* itself when the host's pages cannot be read."""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    home = _get(session, f"https://{host}/")
    locale = _locale(session, host, home)
    search = _get(session, f"https://{host}{locale}/search-results") if locale else None
    if search is None:
        return det
    links = _links(search.text)
    if not any(urlparse(l).netloc.lower() != host for l in links):
        job = next((l for l in links if urlparse(l).netloc.lower() == host and "/job/" in l), None)
        page = _get(session, job) if job else None
        links = _links(page.text) if page is not None else links
    empty: Detection | None = None
    seen: set[tuple[str, str]] = set()
    for link in links:
        if urlparse(link).netloc.lower() == host:
            continue
        found = _follow_link(session, link)
        key = (urlparse(link).netloc.lower(), found.evidence if found else "")
        if found is None or key in seen:
            continue
        seen.add(key)
        if found.entry:
            return Detection(found.platform, found.entry, f"{det.evidence}; its search page links {found.evidence}")
        empty = empty or found
        if len(seen) >= _MAX_LINKS:
            break
    why = f"Phenom front end; the {empty.evidence}" if empty else "Phenom front end; no link to another job system found on its pages"
    return unfollowable("phenom", host, why, "cant_yet")
