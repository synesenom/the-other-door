"""Welcome to the Jungle / Welcome Kit (issue #562): a platform door recognises but does not follow, so it has no `Site`.

French employers publish their jobs on ``welcometothejungle.com/<lang>/companies/<slug>`` (Welcome Kit hosts:
``<x>.welcomekit.co``) or embed the Welcome Kit widget (``welcomekit.co/api/v1/embed?organization_reference=<ref>``)
on their own careers page. Only the detection half of the feed contract (`door.scrapers.sdk`); ``LINK_PLATFORMS`` is
empty because a link to it on a page must not decide which platform the page is on.

Why it is not followed (read 2026-11-01, logged out):
- Terms: ``https://www.welcometothejungle.com/en/pages/terms`` ban automated copying of the site's content, company
  profiles included, so the employer is recorded ``unfollowable`` with ``refusal="must_not"``.
- Its pages answer a script with a bot challenge (HTTP 202, empty body); no public feed is offered.
- Door makes no request to a WTTJ or Welcome Kit host, for detection or otherwise, and does not read the widget's JSON.

What a link or an embed does give is the employer. `resolve` (no request) names it from the company page's slug, or
from the employer's own host when the page carrying the widget is the employer's: `follow` then tries that name on the
public feeds, as for any queued employer. Only when none is found does the employer stay ``unfollowable``."""

import re
from urllib.parse import urlparse

from door.scrapers.sdk import Detection, parts, unfollowable

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("welcometothejungle.com", "welcomekit.co")

LINK_PLATFORMS: tuple[str, ...] = ()
_REASON = ("Welcome to the Jungle: its terms ban automated copying of its pages and company profiles, and its pages "
           "answer a script with a bot challenge; not followed")
_EMBED = re.compile(r"""<(?:script|iframe)\b[^>]*\bsrc\s*=\s*["'](?:https?:)?//(?:[\w-]+\.)*(?:welcomekit\.co|welcometothejungle\.com)/""",
                    re.IGNORECASE)
_SLUG = re.compile(r"^/(?:[a-z]{2}/)?companies/([a-z0-9][a-z0-9-]*)", re.IGNORECASE)
_GENERIC = {"www", "carrieres", "carriere", "careers", "career", "jobs", "job", "recrutement", "emploi", "emplois",
            "recrute", "rejoignez-nous", "talents", "talent", "work"}


def _is_platform(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in PLATFORM_DOMAINS)


def detect_url(url: str) -> Detection | None:
    """A Welcome to the Jungle company page or a Welcome Kit host or widget link."""
    host, _path, _query = parts(url.strip())
    if _is_platform(host):
        return unfollowable("welcometothejungle", host, _REASON, "must_not")
    return None


def detect_html(html: str, url: str) -> Detection | None:
    """A page that embeds the Welcome Kit widget (a script or frame from welcomekit.co or welcometothejungle.com)."""
    if _EMBED.search(html):
        return unfollowable("welcometothejungle", f"{url} embeds the Welcome Kit widget", _REASON, "must_not")
    return None


def _titled(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-") if word)


def employer_name(url: str) -> str | None:
    """The employer a link names without a request: a company page's slug, else the label of the employer's own host
    (``carrieres.acme-industrie.fr`` is ``Acme Industrie``); None for a Welcome Kit host or a bare platform link."""
    host, _path, _query = parts(url.strip())
    if _is_platform(host):
        if host.endswith("welcometothejungle.com"):
            match = _SLUG.match(urlparse(url.strip() if "://" in url else f"https://{url.strip()}").path)
            return _titled(match.group(1)) if match else None
        return None
    labels = [l for l in host.split(".") if l]
    labels = labels[:-1] if len(labels) > 1 else labels   # the top-level domain
    labels = [l for l in labels if l not in _GENERIC] or []
    return _titled(labels[-1]) if labels else None


def resolve(session, det: Detection, url: str) -> Detection:
    """*det* with the employer's name for `follow` to try on the public feeds; *det* itself when the link names none.
    Makes no request."""
    name = employer_name(url)
    if name is None:
        return det
    return Detection(det.platform, None, f"{det.evidence}; the link names the employer {name}", det.refusal, name, None)
