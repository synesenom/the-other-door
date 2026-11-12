"""Ponty (issue #530): a Swedish recruitment system door recognises but does not follow, so it has no `Site`.

Kind: detect-only feed module (only the detection half of the feed contract, `door.scrapers.sdk`).
Where it shows: a Ponty customer's ad is applied for on ``pnty-apply.ponty-system.se/<customer>?id=<n>`` (or
another ``*.ponty-system.se`` host), the link Jobbsafari and Platsbanken ads carry.
Why it is not followed (checked 2026-10-31): those hosts serve one application form per ad (page title and
``<h2>`` name the ad and the hiring employer), with no list of a customer's ads; ``<customer>`` alone is a
"Configuration error" page, the bare ``ponty-system.se`` is a script-only login app, no feed, sitemap or API is
linked, every page is ``noindex, nofollow`` and ``pnty-apply.ponty-system.se/robots.txt`` is ``Disallow: /``.
A customer is often a recruitment agency, so its name is not the hiring employer's either. Employers
listing their own jobs do so on their own career site, which `follow` can still find; the employer is
unfollowable with ``refusal`` "cant_yet" meanwhile. Terms: https://ponty.se (no public terms page for the
application hosts found).
What a form does give is the hiring employer. `resolve` reads that one form (logged out, one request, the page the
applicant sees): its ``<h2 class="sub-legend">`` names the employer the ad is for, which for an agency's customer is the
agency's client (Aldea Executive Search posting for Ponty Technology), never the customer slug. A customer posting for
itself has no such heading; the form's consent text then links the customer's own privacy policy, whose site is the
employer's. When the heading names a client that link is the agency's, so it is used only if the paragraph around it
names the client too. `follow` reads the site for the platform it uses, then tries the name on the public feeds; only
when neither finds a feed does the employer stay unfollowable ("cant_yet"). A form that names no one is left as it is.
`LINK_PLATFORMS` is empty: a link to Ponty on a page does not decide which platform the page is on."""

import html as htmllib
import re
from urllib.parse import urlparse

import requests

from door.scrapers.sdk import Detection, RobotsBlocked, is_job_board, parts, unfollowable

PLATFORM_DOMAINS = ("ponty-system.se",)

LINK_PLATFORMS: tuple[str, ...] = ()
_REASON = "Ponty: an application form per ad, no public job list for the employer; not followed"


def detect_url(url: str) -> Detection | None:
    """A link on ``ponty-system.se`` or one of its subdomains."""
    host, _path, _query = parts(url.strip())
    if host == "ponty-system.se" or host.endswith(".ponty-system.se"):
        return unfollowable("ponty", host, _REASON, refusal="cant_yet")
    return None


def detect_html(html: str, url: str) -> Detection | None:
    """A page that embeds or links Ponty's application form."""
    if "ponty-system.se/" in html:
        return unfollowable("ponty", f"{url} embeds a Ponty form", _REASON, refusal="cant_yet")
    return None


_NAME = re.compile(r"""<h2\b[^>]*\bclass\s*=\s*["'][^"']*\bsub-legend\b[^"']*["'][^>]*>(.*?)</h2>""", re.IGNORECASE | re.DOTALL)
_CONSENT = re.compile(r"""<div\b[^>]*\bclass\s*=\s*["'][^"']*\bconsent-wrapper\b[^"']*["'][^>]*>(.*)""", re.IGNORECASE | re.DOTALL)
_PARAGRAPH = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
# The vendor's own sites are never an employer's.
_NOT_EMPLOYER = ("ponty.se", "ponty-system.se")


def _plain(markup: str) -> str:
    return " ".join(htmllib.unescape(_TAGS.sub(" ", markup)).split())


def _site(link: str) -> str | None:
    """The origin of *link* when it is a web link to an employer's own site: no mail link, vendor or job board host."""
    link = htmllib.unescape(link).strip()
    if not re.match(r"https?://", link, re.IGNORECASE):
        return None
    host = urlparse(link).netloc.lower()
    if not host or any(host == d or host.endswith("." + d) for d in _NOT_EMPLOYER) or is_job_board(link):
        return None
    return f"{urlparse(link).scheme.lower()}://{host}"


def employer_of(html: str) -> tuple[str | None, str | None]:
    """``(name, site)`` of the employer an apply form names; None for what it does not give.

    The name is the form's sub-heading (the client an agency hires for). The site is the first employer-like link of
    the consent text, kept when the form names no client (the customer is the employer) or the link's paragraph
    names the client (an agency's policy link is not the client's site)."""
    found = _NAME.search(html or "")
    name = _plain(found.group(1)) or None if found else None
    consent = _CONSENT.search(html or "")
    for paragraph in _PARAGRAPH.findall(consent.group(1)) if consent else ():
        for href in _HREF.findall(paragraph):
            site = _site(href)
            if site and (name is None or name.casefold() in _plain(paragraph).casefold()):
                return name, site
    return name, None


def resolve(session, det: Detection, url: str) -> Detection:
    """*det* (a link on ``ponty-system.se``) with the employer the apply form names: its name and website, for
    `follow` to try. *det* itself for a link that is no apply form (no ``id``), and when the form cannot be read or
    names no employer."""
    host, _path, query = parts(url.strip())
    if "id" not in query or not (host == "ponty-system.se" or host.endswith(".ponty-system.se")):
        return det
    try:
        response = session.get(url.strip())
        if response.status_code != 200:
            return det
        name, site = employer_of(response.text)
    except (requests.RequestException, RobotsBlocked):
        return det
    if name is None and site is None:
        return det
    return Detection(det.platform, None, f"{det.evidence}; the form names the employer {name or site}",
                     det.refusal, name, site)
