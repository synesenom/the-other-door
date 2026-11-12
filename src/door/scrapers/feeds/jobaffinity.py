"""Jobaffinity (issue #563): a French recruitment system (publisher Intuition) door recognises but does not follow, so it has no `Site`.

Kind: detect-only feed module (only the detection half of the feed contract, `door.scrapers.sdk`).
Where it shows: a customer's ad is applied for on ``jobaffinity.fr/apply/<token>`` (the link public-sector ads
multiposted to France Travail carry).
Why it is not followed (checked 2026-11-01): that page is a server-rendered application form for one ad (title,
"Dossier de candidature", the fields, a data-protection notice) with no ad text, no JSON-LD and no list of the
customer's ads; no public list, feed or sitemap was found. The documented REST API (api.jobaffinity.com,
``jobaffinity.fr/restapi/v1``) needs a customer key, which door never uses. ``jobaffinity.fr/robots.txt`` is
``Disallow: /`` for the bots it names. The employer is unfollowable with ``refusal`` "cant_yet" meanwhile. Terms:
https://jobaffinity.fr (no public terms page for the apply form found).
What the form does give is the hiring employer. `resolve` reads that one form (logged out, one request, the page the
applicant sees): its data-protection notice names the data controller ("traitement automatisé par ICCI Formations,
..., en sa qualité de responsable de traitement"), which is the employer. The form links no website of its own, so
`follow` tries the name on the public feeds; when none has it the employer stays unfollowable ("cant_yet"). A form
that names no one is left as it is.
`LINK_PLATFORMS` is empty: a link to Jobaffinity on a page does not decide which platform the page is on."""

import html as htmllib
import re

import requests

from door.scrapers.sdk import Detection, RobotsBlocked, parts, unfollowable

PLATFORM_DOMAINS = ("jobaffinity.fr", "jobaffinity.com")

LINK_PLATFORMS: tuple[str, ...] = ()
_REASON = "Jobaffinity: an application form per ad, no public job list for the employer; not followed"


def _is_jobaffinity(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in PLATFORM_DOMAINS)


def detect_url(url: str) -> Detection | None:
    """A link on ``jobaffinity.fr`` / ``jobaffinity.com`` or one of their subdomains."""
    host, _path, _query = parts(url.strip())
    if _is_jobaffinity(host):
        return unfollowable("jobaffinity", host, _REASON, refusal="cant_yet")
    return None


_APPLY_LINK = re.compile(r"https?://(?:[\w-]+\.)*jobaffinity\.(?:fr|com)/apply/", re.IGNORECASE)


def detect_html(html: str, url: str) -> Detection | None:
    """A page that links or embeds a Jobaffinity application form."""
    if _APPLY_LINK.search(html or ""):
        return unfollowable("jobaffinity", f"{url} links a Jobaffinity form", _REASON, refusal="cant_yet")
    return None


_CONTROLLER = re.compile(r"(?:traitement\s+automatisé|traité(?:e|s|es)?)\s+par\s+([^,.;<]+?)\s*[,.;]", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def employer_of(html: str) -> str | None:
    """The employer an apply form names as its data controller; None for a form that names no one."""
    text = " ".join(htmllib.unescape(_TAGS.sub(" ", html or "")).split())
    found = _CONTROLLER.search(text)
    return (found.group(1).strip() or None) if found else None


def resolve(session, det: Detection, url: str) -> Detection:
    """*det* (a link on Jobaffinity) with the employer the apply form names, for `follow` to try by name.
    *det* itself for a link that is no apply form, and when the form cannot be read or names no one."""
    host, path, _query = parts(url.strip())
    if not _is_jobaffinity(host) or path[:1] != ["apply"]:
        return det
    try:
        response = session.get(url.strip())
        if response.status_code != 200:
            return det
        name = employer_of(response.text)
    except (requests.RequestException, RobotsBlocked):
        return det
    if name is None:
        return det
    return Detection(det.platform, None, f"{det.evidence}; the form names the employer {name}",
                     det.refusal, name, None)
