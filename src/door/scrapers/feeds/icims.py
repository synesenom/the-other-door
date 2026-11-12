"""iCIMS (issue #603): a career-portal platform door recognises but does not follow, so it has no `Site`.

Kind: detect-only feed module (only the detection half of the feed contract, `door.scrapers.sdk`).
Where it shows: a customer's portal is ``<prefix>-<tenant>.icims.com`` (``careers-sisk``, ``uscareers-pepsico``,
``unitedstates-aon``) or a custom domain that is a CNAME for one (that domain is the employer's own host, which `career_sites` reads
as before); its ads are ``/jobs/<id>/<slug>/job`` and its
list ``/jobs/search`` (``?ss=1&in_iframe=1``, paged by ``pr=<n>``), logged out and without a key.
Why it is not followed (read 2026-11-04): the public list and the ads' JSON-LD would be readable, but iCIMS's
terms of use (https://www.icims.com/legal/terms-of-use/) define the "Website" as ``www.icims.com or its related
domains and subdomains`` and bar anyone from using "any robot, spider or other automatic device, process, or means
to access the Website ... including monitoring or copying any of the material", and the hosted portals are
subdomains of ``icims.com``; the Jobmagic terms (https://social.icims.com/legal/terms) say the same of that service.
A portal's pages link no terms of their own. robots.txt of a portal (``careers-sisk.icims.com``) disallows only
login, referral, candidate and ``/connect`` paths, which does not gate requests here (``http_client.OBEY_ROBOTS``);
the terms are what rules it out. The employer is unfollowable with ``refusal`` "must_not". Door sent nothing to an
iCIMS host while this module runs, for detection or otherwise: a link is read as text.
What a portal host does give is the employer: ``careers-sisk.icims.com`` is Sisk. `resolve` (no request) names it
for `follow` to try on the public feeds, as for any queued employer; only when none is found does the employer stay
``unfollowable``.
`LINK_PLATFORMS` is empty: a link to iCIMS on a page (an apply link) does not decide which platform the page is on,
since the employer's own list may be read some other way."""

import re

from door.scrapers.sdk import Detection, NOT_ACCOUNTS, parts, unfollowable

# The platform's own domain: a host on it is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("icims.com",)

LINK_PLATFORMS: tuple[str, ...] = ()
_REASON = ("iCIMS: its terms of use bar robots and other automatic means on icims.com and its subdomains, where every "
           "portal is hosted; not followed")
_SUFFIX = ".icims.com"
# The vendor's own hosts (marketing, community, static assets, its provider servers): no customer portal.
_NOT_PORTALS = NOT_ACCOUNTS | {"community", "social", "marketplace", "developer-community", "developer", "help", "support",
                               "status", "login", "mail", "static"}
_NOT_PORTAL_PATTERN = re.compile(r"^(?:cdn\d*|provider-.+|images?\d*|content\d*)$")
# What a portal's label starts with before the tenant: careers-, uscareers-, ... and a region (unitedstates-aon).
_PREFIX = re.compile(r"^(?:[a-z]*(?:careers?|jobs?)|external|internal|apply|recruiting|us|uk|eu|emea|global|"
                     r"unitedstates|unitedkingdom|ireland|canada|australia)-(?=.)")


def _tenant_label(host: str) -> str | None:
    """The portal's label (``careers-sisk``) of an ``icims.com`` host, None for the vendor's own hosts. Pure."""
    label = host[: -len(_SUFFIX)] if host.endswith(_SUFFIX) else ""
    if not label or "." in label or label in _NOT_PORTALS or _NOT_PORTAL_PATTERN.match(label):
        return None
    return label


def detect_url(url: str) -> Detection | None:
    """A link on a customer's iCIMS portal (``<prefix>-<tenant>.icims.com``)."""
    host, _path, _query = parts(url.strip())
    if _tenant_label(host) is not None:
        return unfollowable("icims", host, _REASON)
    return None


def employer_name(url: str) -> str | None:
    """The employer a portal host names (``careers-sisk.icims.com`` is ``Sisk``, ``unitedstates-aon`` ``Aon``);
    None for the vendor's own hosts and other domains. Makes no request. Pure."""
    label = _tenant_label(parts(url.strip())[0])
    if label is None:
        return None
    label = _PREFIX.sub("", label, count=1)
    return " ".join(word.capitalize() for word in label.split("-") if word) or None


def resolve(session, det: Detection, url: str) -> Detection:
    """*det* with the employer the portal host names, for `follow` to try on the public feeds; *det* itself for a
    link that names none. Makes no request to iCIMS."""
    name = employer_name(url)
    if name is None:
        return det
    return Detection(det.platform, None, f"{det.evidence}; the host names the employer {name}", det.refusal, name, None)
