"""The employer list's commands: `companies` (list), `companies add`, `remove` and `why`, and the
detection behind them (issue #233, restructure phase A).

`_resolve_core` turns a company name, a careers link or a career host into the feed it
belongs to, from public signals only: the link's own shape, the host's DNS CNAME, the
careers page (one polite GET, robots.txt honoured), and for a bare name a probe of each
feed's public endpoint with the name's likely slugs (Greenhouse -> Lever US, then EU -> Ashby
-> Recruitee -> Pinpoint -> Teamtailor -> Workable -> SmartRecruiters) and of its likely career hosts' CNAMEs.
`_add_core` records what it finds in `profile/companies.json` (`door.core.companies`),
unfollowable and unresolved employers too, with the reason.

`_classify` runs the same detection over a queued candidate's links (and name); `follow`
(`door.pipeline.follow`) calls it for every employer in the candidates queue. A name that none of this
resolves is looked up on Wikidata (`door.core.wikidata`, #566) for the employer's own website, whose careers
pages, careers hosts and platform tenants are then read the same way (`_by_website`).
"""

import importlib
import json
import re
import sys
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import click
import requests

from door import i18n
from door.commands import _common as common
from door.core import ats_detect, sites, wikidata, workspace
from door.core import companies as store
from door.scrapers.feeds import hr_manager
from door.scrapers.http_client import PoliteSession, RobotsBlocked

_HOST_GUESSES = ("careers.{s}.com", "jobs.{s}.com")
# Host labels an employer's careers site is tried under on its own website's domain ("career.hm.com", #566).
_SITE_LABELS = ("careers", "career", "jobs", "job")


def _career_labels(words: list[str]) -> list[str]:
    """The one-word host labels among *words*, in ASCII. Pure."""
    return [label for w in words if w.strip() and " " not in w.strip() for label in [i18n.slug_spellings(w)[-1]] if label]


def _country_labels(country) -> list[str]:
    """The career host labels of *country*: its ``career_hosts`` and each one-word career-site word of its
    languages (``karriere``). Pure."""
    packs = i18n.languages()
    return [*country.career_hosts,
            *(w for code in country.languages if code in packs for w in packs[code].career_site_words)]


def _host_guesses(location: str) -> tuple[str, ...]:
    """The career hosts an employer's name is tried on (``{s}``: a slug of the name): `_HOST_GUESSES`
    anywhere, and in the country *location* names (with a file in `i18n/country/`) its own domain
    (``tlds``, else its ISO code), under ``careers``, ``jobs``, its ``career_hosts`` and each one-word
    career-site word of its languages (``karriere``). Pure."""
    country = i18n.country_for_location(location or "")
    if country is None:
        return _HOST_GUESSES
    labels = _career_labels(["careers", "jobs", *_country_labels(country)])
    tld = country.tlds[0] if country.tlds else country.code
    return tuple(dict.fromkeys([*_HOST_GUESSES, *(f"{w}.{{s}}.{tld}" for w in labels)]))


def _site_labels(location: str) -> tuple[str, ...]:
    """The host labels a careers site is tried under on an employer's own domain: `_SITE_LABELS`, and those of
    the country *location* names (`_country_labels`). Pure."""
    country = i18n.country_for_location(location or "")
    extra = _country_labels(country) if country is not None else []
    return tuple(dict.fromkeys(_career_labels([*_SITE_LABELS, *extra])))


def _domain(site: str) -> str:
    """The domain of a website, without the labels that name no employer ("www2.hm.com" -> "hm.com"). Pure."""
    host = ats_detect.safe_urlparse(site if "://" in site else f"https://{site}").netloc.lower().split(":")[0]
    labels = host.split(".")
    generic = set(i18n.generic_host_labels())
    while len(labels) > 2 and (re.fullmatch(r"www\d*", labels[0]) or labels[0] in generic):
        labels = labels[1:]
    return ".".join(labels)


def _site_hosts(site: str, labels: tuple[str, ...]) -> list[str]:
    """The careers hosts tried on a website's domain (``career.hm.com`` for ``www2.hm.com``). Pure."""
    domain = _domain(site)
    own = ats_detect.safe_urlparse(site if "://" in site else f"https://{site}").netloc.lower()
    return [h for h in dict.fromkeys(f"{label}.{domain}" for label in labels) if h != own]


def _cname(host: str) -> str | None:
    """The DNS CNAME of *host*, or None. Read-only; patched in tests."""
    try:
        import dns.resolver

        answer = dns.resolver.resolve(host, "CNAME", lifetime=5)
        return str(answer[0].target).rstrip(".")
    except Exception:  # noqa: BLE001 - no CNAME, no such host, no DNS: all "unknown"
        return None


def _resolves(host: str) -> bool:
    """Whether *host* exists in DNS. Read-only; patched in tests."""
    try:
        import dns.resolver

        dns.resolver.resolve(host, "A", lifetime=5)
        return True
    except Exception:  # noqa: BLE001
        return False


def _feed_module(platform: str):
    """The platform's module under `door.scrapers.feeds`, for its `feed_url` (None for a platform it has none)."""
    return importlib.import_module(f"door.scrapers.feeds.{platform}")


def _feed_check(platform: str, entry: str) -> tuple[str, str | None] | None:
    """``(url, key)`` of the feed that confirms *entry* by listing jobs, or None when the platform
    needs none (`feed_url` of the platform's module)."""
    module = _feed_module(platform)
    url = module.feed_url(entry) if hasattr(module, "feed_url") else None
    return (url, getattr(module, "FEED_KEY", None)) if url else None


def _confirmed(session: PoliteSession, det: ats_detect.Detection | None) -> ats_detect.Detection | None:
    """*det*, unless it is a signature-based custom-host entry whose feed lists no jobs."""
    if det is None or not det.entry or "." not in det.entry:
        return det
    check = _feed_check(det.platform, det.entry)
    if check is None:
        return det
    if _has_jobs(session, *check):
        return ats_detect.Detection(det.platform, det.entry, f"{det.evidence}; its feed lists open jobs")
    return None


def _look_through(session: PoliteSession | None, det: ats_detect.Detection | None, url: str) -> ats_detect.Detection | None:
    """*det*, read further by its platform module's ``resolve(session, det, url)`` when it has one (a link
    into an inactive site, a front end for another system); the platform names its own rules (#438).
    *det* itself without a session."""
    if session is None or det is None:
        return det
    hook = getattr(_feed_module(det.platform), "resolve", None)
    return hook(session, det, url) if hook is not None else det


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.3, max_delay=0.6, timeout=15, max_retries=0)


def _fetch_jobs(session: PoliteSession, url: str, key: str | None, params: dict | None = None) -> list:
    """The job list *url* answers with (under *key*, or a bare list); empty when it answers nothing usable."""
    try:
        data = session.get(url, params=params, headers={"Accept": "application/json"}).json()
    except (requests.RequestException, RobotsBlocked, ValueError):
        return []
    items = data if key is None else (data.get(key) if isinstance(data, dict) else None)
    return items if isinstance(items, list) else []


def _has_jobs(session: PoliteSession, url: str, key: str | None, params: dict | None = None) -> bool:
    """Whether *url* answers with a non-empty job list (under *key*, or a bare list)."""
    return bool(_fetch_jobs(session, url, key, params))


@dataclass
class FeedJobs:
    """The job lists of the feeds found by name in one run, to tell a shared demo account: two employers
    whose feeds list the same jobs (Novo Nordisk's and KPMG's Pinpoint tenants, #435)."""

    claimed: dict = field(default_factory=dict)   # (platform, fingerprint) -> the first employer's name
    collided: set = field(default_factory=set)    # the names whose feed another name's feed duplicates
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def claim(self, platform: str, items: list, name: str) -> str | None:
        """The other employer whose feed lists these same jobs, else None (and *name* claims them)."""
        fingerprint = ats_detect.feed_fingerprint(items)
        if fingerprint is None:
            return None
        with self._lock:
            other = self.claimed.setdefault((platform, fingerprint), name)
            if store.name_key(other) == store.name_key(name):
                return None
            self.collided.update({other, name})
            return other


def _probe_name(
    session: PoliteSession, name: str, confirm: Callable[[list], str | None] | None = None,
    notes: list[str] | None = None, hosts: tuple[str, ...] = _HOST_GUESSES, jobs: FeedJobs | None = None,
) -> ats_detect.Detection | None:
    """Each feed's public endpoint with the name's likely slugs, then its likely career hosts.

    A feed that looks like a platform's demo account (`ats_detect.feed_looks_demo`), or lists the same jobs
    as another name's feed (*jobs*), is never followed. With *confirm* (a check of the feed's jobs that
    returns why they are this employer's, or None) a feed that lists jobs but fails the check is a
    namesake's, not followed. *notes* collects why each was passed over.
    """
    slugs = ats_detect.slug_candidates(name)
    for platform, slug, probe in ats_detect.name_probes(slugs):
        items = _fetch_jobs(session, probe.url, probe.key, probe.params)
        if not items:
            continue
        demo = ats_detect.feed_looks_demo(items)
        if demo is not None:
            if notes is not None:
                notes.append(f"{probe.evidence} lists jobs, but it looks like a demo or sample account ({demo})")
            continue
        other = jobs.claim(platform, items, name) if jobs is not None else None
        if other is not None:
            if notes is not None:
                notes.append(f"{probe.evidence} lists the same jobs as {other}'s feed (a shared demo account?)")
            continue
        why = confirm(items) if confirm is not None else None
        if confirm is not None and why is None:
            if notes is not None:
                notes.append(f"{probe.evidence} lists jobs, but none matches a queued job title or the profile's location (another company's?)")
            continue
        tail = f"; {why}" if why else ""
        return ats_detect.Detection(platform, slug, f"{probe.evidence} lists open jobs{tail}")
    for slug in slugs:
        for pattern in hosts:
            host = pattern.format(s=slug)
            det = _look_through(session, ats_detect.from_cname(host, _cname(host) or ""), f"https://{host}/")
            if det is None and _resolves(host):
                det = _page_detection(session, f"https://{host}/")
            if det is not None:
                return det
    return None


def _by_employer(
    session: PoliteSession, det: ats_detect.Detection, confirm: Callable[[list], str | None] | None,
    notes: list[str], ctx: "Context",
) -> ats_detect.Detection | None:
    """The feed of the employer a look-through named (*det*'s ``site`` and ``employer``, #526): the platform
    its own website shows, else the feeds its name probes find, each checked as for any employer. None when
    neither finds one."""
    found = None
    if det.site:
        found = _confirm(session, _detect_link(session, det.site))
        found = found if found is not None and found.entry else None
    if found is None and det.employer:
        found = _probe_name(session, det.employer, confirm, notes, ctx.hosts, ctx.jobs)
    if found is None:
        return None
    return replace(found, evidence=f"{det.evidence} → {found.evidence}")


def _tenant_slugs(found: "wikidata.Employer") -> list[str]:
    """The tenant names an employer Wikidata knows may have on a platform: its name's and its parent's, and its
    websites' domain names ("teliacompany" for Telia Sverige, whose group is Telia Company). Pure."""
    slugs = [ats_detect.slug_candidates(name)[:1] for name in found.names()]
    domains = [[_domain(site).split(".")[0]] for site in found.sites()]
    return [s for s in dict.fromkeys(x for group in [*slugs, *domains] for x in group) if s]


def _by_website(
    session: PoliteSession, name: str, notes: list[str], ctx: "Context",
) -> ats_detect.Detection | None:
    """The feed an employer's own website leads to, the website read from Wikidata by the employer's name
    (`ctx.employers`, #566): the website (then its parent organisation's) and the careers pages it links to, the
    careers hosts of its domain (``career.hm.com``), then each platform's tenant named like it (Workday's
    ``teliacompany``). A found feed is checked as any link's; a platform that cannot be followed is the answer
    only when nothing else is found. None (and a note in *notes*) when none shows a feed."""
    if ctx.employers is None:
        return None
    found, why = ctx.employers.employer(session, name)
    if found is None:
        if why:
            notes.append(why)
        return None
    origin = f"Wikidata {found.qid} ({found.label})"
    fallback = None
    for site in found.sites():
        det = _confirm(session, _detect_link(session, site))
        if det is not None and det.entry:
            return replace(det, evidence=f"{origin} names its website {site} → {det.evidence}")
        fallback = fallback or det
        for host in _site_hosts(site, ctx.site_labels):
            if not (_cname(host) or _resolves(host)):
                continue
            det = _confirm(session, _detect_link(session, f"https://{host}/"))
            if det is not None and det.entry:
                return replace(det, evidence=f"{origin} names its website {site} → {host} → {det.evidence}")
            fallback = fallback or det
    for slug in _tenant_slugs(found):
        for probe in ats_detect.tenant_probes():
            det = probe(session, slug)
            if det is not None and det.entry:
                return replace(det, evidence=f"{origin} → {det.evidence}")
    shown = ", ".join(found.sites()) or "no website"
    notes.append(f"{origin}: {shown}, but no job feed was found there")
    return fallback


def _page_detection(session: PoliteSession, url: str) -> ats_detect.Detection | None:
    """What a careers page shows (one polite GET, robots.txt honoured), confirmed by its feed."""
    try:
        resp = session.get(url, headers={"Accept": "text/html"})
    except (requests.RequestException, RobotsBlocked):
        return None
    det = ats_detect.from_html(resp.text, resp.url or url) or ats_detect.from_url(resp.url or "")
    return _confirmed(session, det)


# How far `_detect_link` follows an employer's careers links: pages tried from the
# page it was given, then pages tried from the first careers page that links on.
_MAX_CAREERS_PAGES = 4
_MAX_SECOND_HOP = 3


@dataclass
class Context:
    """What the detection of many employers shares: the HR-Manager customers already looked up, the
    aliases the list follows (their customer numbers are learned once), the places the profile looks
    in, and the question to ask when every check failed (`ai`: company dict -> careers URL or None)."""

    hr_by_cid: dict = field(default_factory=dict)
    hr_aliases: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    hosts: tuple[str, ...] = _HOST_GUESSES   # career hosts a name is tried on (`_host_guesses`)
    site_labels: tuple[str, ...] = _SITE_LABELS  # careers host labels on an employer's own domain (`_site_labels`)
    employers: wikidata.Lookup | None = None    # the employers' websites by name (#566); None: not looked up
    ai: Callable[[dict], str | None] | None = None
    jobs: FeedJobs = field(default_factory=FeedJobs)  # the job lists of the feeds found by name (a shared demo)
    _cids: dict | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _inspect(session: PoliteSession, url: str) -> tuple[ats_detect.Detection | None, str | None, str]:
    """What one URL shows: ``(detection, html, final url)``. Its shape, its host's CNAME,
    then its page (one polite GET, robots.txt honoured; ``html`` None when skipped)."""
    det = ats_detect.from_url(url)
    if det is not None:
        if det.platform == "hr_manager" and det.entry is None:
            det = _hr_alias_from_ad(session, url) or det
        return _confirm(session, _look_through(session, det, url)), None, url
    host = ats_detect.safe_urlparse(url).netloc.lower()
    det = ats_detect.from_cname(host, _cname(host) or "")
    if det is not None:
        return _confirm(session, _look_through(session, det, url)), None, url
    try:
        resp = session.get(url, headers={"Accept": "text/html"})
    except (requests.RequestException, RobotsBlocked):
        return None, None, url
    final = resp.url or url
    det = ats_detect.from_html(resp.text, final) or ats_detect.from_url(final)
    return _confirm(session, _look_through(session, det, final)), resp.text, final


def _arrow(origin: str, det: ats_detect.Detection, via: list[str]) -> ats_detect.Detection:
    """*det* with the path that led to it in front of its evidence."""
    return replace(det, evidence=" → ".join([origin, *via, det.evidence]))


def _note_listing(listings: list, html: str | None, url: str, hint: str | None) -> None:
    """Remember *url* as a listing page when it links job ads (see `ats_detect.listing_detection`)."""
    det = ats_detect.listing_detection(html, url, hint) if html else None
    if det is not None:
        listings.append((len(ats_detect.ad_links(html, url)), det))


def _follow_careers(
    session: PoliteSession, origin: str, page_url: str, html: str, seen: set[str],
    listings: list | None = None, hint: str | None = None,
) -> ats_detect.Detection | None:
    """The job system behind the careers links of *page_url* (whose markup is *html*).

    Tries the page's best careers links; if none shows a platform, tries the links of
    the first of those pages that has any. Stops at the first detection. A page that
    lists job ads is noted in *listings* on the way.
    """
    listings = [] if listings is None else listings
    hop_one = [u for u in ats_detect.career_links(html, page_url) if u not in seen][:_MAX_CAREERS_PAGES]
    next_hop: tuple[str, str] | None = None
    for url in hop_one:
        seen.add(url)
        det, page, final = _inspect(session, url)
        if det is not None:
            return _arrow(origin, det, [])
        _note_listing(listings, page, final, hint)
        if page is not None and next_hop is None and ats_detect.career_links(page, final):
            next_hop = (final, page)
    if next_hop is None:
        return None
    hop_two = [u for u in ats_detect.career_links(next_hop[1], next_hop[0]) if u not in seen][:_MAX_SECOND_HOP]
    for url in hop_two:
        seen.add(url)
        det, page, final = _inspect(session, url)
        if det is not None:
            return _arrow(origin, det, [next_hop[0]])
        _note_listing(listings, page, final, hint)
    return None


def _detect_link(session: PoliteSession | None, link: str, pages: dict | None = None) -> ats_detect.Detection | None:
    """A careers link or host: its shape, its host's CNAME, then (with a session) its page,
    then the careers pages that page links to; for a deep link on an employer's own site,
    the same from the site's home page. A site no platform shows is followed through the careers
    page that lists its job ads as links (the page with the most), when one does. The link's own
    page, when read, is left in *pages* under ``"html"`` (it names the employer, #436)."""
    link = link.strip()
    det = ats_detect.from_url(link)
    if det is not None:
        return _look_through(session, det, link)
    if ats_detect.is_job_board(link) or ats_detect.is_shared_ats_host(link):
        return None
    url = link if "://" in link else f"https://{link}"
    host = ats_detect.safe_urlparse(url).netloc.lower()
    det = ats_detect.from_cname(host, _cname(host) or "")
    if det is not None or session is None or host.endswith("hr-manager.net"):
        return _look_through(session, det, url)
    listings: list = []
    hint = link if "://" in link else None
    det, html, final = _inspect(session, url)
    if pages is not None and html:
        pages["html"] = html
    if det is not None:
        return det
    _note_listing(listings, html, final, hint)
    seen = {url, final}
    if html is not None:
        det = _follow_careers(session, host, final, html, seen, listings, hint)
        if det is not None:
            return det
    parsed = ats_detect.safe_urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}/"
    if parsed.path.strip("/") and root not in seen and not ats_detect.is_job_board(url):
        seen.add(root)
        det, html, final = _inspect(session, root)
        if det is not None:
            return _arrow(host, det, [])
        if html is not None:
            det = _follow_careers(session, host, final, html, seen, listings, hint)
            if det is not None:
                return det
    if listings:
        count, best = max(listings, key=lambda item: item[0])
        return _arrow(host, best, [])
    return None


# --------------------------------------------------------------------------- #
# HR-Manager: the customer behind an application link (cid=...)
# --------------------------------------------------------------------------- #

def _hr_known_cids(session: PoliteSession, ctx: Context) -> dict[str, str]:
    """``{customer number: alias}`` of the HR-Manager aliases the employer list follows, learned once
    from one position of each feed."""
    with ctx._lock:
        if ctx._cids is None:
            known: dict[str, str] = {}
            for alias in ctx.hr_aliases:
                for item in hr_manager.feed_items(session, alias):
                    cid = hr_manager.hr_manager_item_cid(item)
                    if cid:
                        known.setdefault(cid, alias)
            ctx._cids = known
        return ctx._cids


def _hr_by_cid(session: PoliteSession, link: str, cid: str, ctx: Context) -> ats_detect.Detection | None:
    """The HR-Manager customer of an application link: one already followed with that customer number
    (no page is read), else what its ad page leads to. Cached per customer number."""
    if cid in ctx.hr_by_cid:
        return ctx.hr_by_cid[cid]
    shared = hr_manager.shared_alias_for_cid(cid)  # the state portal: known by its number, no page to read
    alias = shared or _hr_known_cids(session, ctx).get(cid)
    if shared is not None:
        det = ats_detect.Detection("hr_manager", shared, f"HR-Manager customer {cid} ({link}) is the shared portal {shared}")
    elif alias is not None:
        det = ats_detect.Detection("hr_manager", alias, f"HR-Manager customer {cid} ({link}) is the customer of {alias}, which is followed")
    else:
        det = hr_manager.alias_from_ad(session, link, _detect_link)
    ctx.hr_by_cid[cid] = det
    return det


def _expand_short(session: PoliteSession, link: str) -> str:
    """The page a Talentech short link (``go.talentech.io/<code>``) redirects to: one request, read from the
    ``original_apply_url`` of its redirect; *link* itself when it is no short link or does not resolve."""
    if not ats_detect.is_short_link(link):
        return link
    try:
        target = session.redirect_target(link)
    except (requests.RequestException, RobotsBlocked):
        return link
    return ats_detect.unwrap_redirect(target or "") or link


def _confirm(session: PoliteSession, det: ats_detect.Detection | None) -> ats_detect.Detection | None:
    """*det*, if it holds up: an entry named by a link's shape on a platform with a `feed_url`
    (Teamtailor, Recruitee, Pinpoint) needs a feed that lists jobs (a dead subdomain is dropped), a custom
    host is checked by `_confirmed`."""
    if det is None or not det.entry:
        return det
    check = _feed_check(det.platform, det.entry)
    if check is not None and "." not in det.entry:
        if not _has_jobs(session, *check):
            return None
        return ats_detect.Detection(det.platform, det.entry, f"{det.evidence}; its feed lists open jobs")
    return _confirmed(session, det)


def _looks_like_link(text: str) -> bool:
    text = text.strip()
    return "://" in text or (" " not in text and "." in text)


def _result(text: str, det: ats_detect.Detection | None, notes: list[str] | None = None) -> dict:
    if det is None:
        return {"input": text, "platform": None, "entry": None, "config_key": None,
                "candidates": [] if _looks_like_link(text) else ats_detect.slug_candidates(text),
                "notes": list(notes or [])}
    return {"input": text, "platform": det.platform, "entry": det.entry, "config_key": det.config_key,
            "evidence": det.evidence, "refusal": det.refusal, "notes": list(notes or [])}


def _dead_feed(session: PoliteSession | None, det: ats_detect.Detection | None) -> str | None:
    """Why *det*'s feed is dead: its first read (the platform module's `alive_url`) answers a 4xx, as an
    HR-Manager alias that no longer exists does; None when it answers, has no such check, or the read
    fails otherwise (no answer is no verdict) (#435)."""
    if session is None or det is None or not det.entry or store.shared_name(det.platform, det.entry):
        return None  # (a shared portal's feed is known: no read)
    module = _feed_module(det.platform)
    url = module.alive_url(det.entry) if hasattr(module, "alive_url") else None
    if not url:
        return None
    try:
        session.get(url, headers={"Accept": "application/json"})
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if 400 <= status < 500:
            return f"{det.evidence}, but its feed answers {status} (the account no longer exists?)"
    except (requests.RequestException, RobotsBlocked):
        pass
    return None


def _name_confirm(titles: list[str], places: list[str]) -> Callable[[list], str | None] | None:
    """The check a feed found by the employer's name alone must pass: a queued job title is among its
    jobs, or one is in the profile's place; None (no check beyond the demo one) with nothing to compare."""
    if not titles and not places:
        return None
    return lambda items: ats_detect.feed_confirms(items, titles, places)


def _link_names_employer(det: ats_detect.Detection) -> bool:
    """Whether the platform's career page names the employer the link's shape does not (Emply: the
    tenant slug is no name), so the page is read for it (the platform module's `NAME_FROM_PAGE`)."""
    return bool(det.entry) and bool(getattr(_feed_module(det.platform), "NAME_FROM_PAGE", False))


def _name_page(det: ats_detect.Detection, link: str) -> str:
    """The page that names the employer: *link*, unless the platform's module says an ad link is the wrong
    page (``name_page(entry, link)``: Varbi's ad page is titled by the job, its board page by the employer)."""
    hook = getattr(_feed_module(det.platform), "name_page", None)
    return hook(det.entry, link) if hook is not None else link


def _read_page(session: PoliteSession, link: str, pages: dict) -> None:
    """The page of *link* into *pages* under ``"html"``; nothing when it cannot be read."""
    url = link if "://" in link else f"https://{link}"
    try:
        pages["html"] = session.get(url, headers={"Accept": "text/html"}).text
    except (requests.RequestException, RobotsBlocked):
        pass


def _resolve_core(inputs: list[str], *, probe: bool = True, location: str = "") -> dict:
    """Resolve each company name, careers link or career host to its feed entry. Never prints, writes nothing.

    Returns:
        ``{"results": [{"input", "platform", "entry", "config_key", "evidence"
        | "candidates", "page_name"}]}`` — ``platform`` with ``entry`` None is a platform
        The other door cannot follow (``evidence`` says why); ``platform`` None is not
        found (``candidates``: the slugs tried for a name); ``page_name`` is the employer
        a link's page names (`store.name_from_page`), "" when it names none or was not read.
    """
    session = _session() if probe else None
    confirm = _name_confirm([], ats_detect.places_for(location))
    jobs = FeedJobs()
    ctx = Context(hosts=_host_guesses(location), site_labels=_site_labels(location), jobs=jobs,
                  employers=wikidata.Lookup(location) if probe else None)
    results, by_name = [], []
    for text in (t for t in inputs if t.strip()):
        pages: dict = {}
        notes: list[str] = []
        if _looks_like_link(text):
            det = _detect_link(session, text, pages)
        else:
            det = _probe_name(session, text, confirm, notes, ctx.hosts, jobs) if session is not None else None
            if det is None and session is not None:
                det = _by_website(session, text, notes, ctx)
            by_name.append(len(results))
        dead = _dead_feed(session, det)
        if dead is not None:
            det, notes = None, [*notes, dead]
        if det is not None and session is not None and "html" not in pages and _link_names_employer(det):
            _read_page(session, _name_page(det, text.strip()), pages)
        results.append({**_result(text.strip(), det, notes), "page_name": store.name_from_page(pages.get("html", ""))})
    for i in by_name:  # a feed another name also found: a shared demo, followed by neither
        if results[i]["input"] in jobs.collided and results[i]["entry"]:
            note = f"{results[i]['evidence']}, but another name's feed lists the same jobs (a shared demo account?)"
            results[i] = {**_result(results[i]["input"], None, [*results[i]["notes"], note]),
                          "page_name": results[i]["page_name"]}
    return {"results": results}


def _name_for(result: dict) -> str:
    """The employer's name for a resolved input: the input itself when it is a name, else the name its
    page gives, else a guess from the feed entry (or the link): a tenant, never the platform (#436)."""
    text = result["input"]
    if not _looks_like_link(text):
        return text
    return result.get("page_name") or store.guess_name(result.get("entry") or text)


@common._locked("companies add")
def _add_core(
    inputs: list[str], *, dry_run: bool = False, probe: bool = True,
    profile_dir: Path | None = None, jobs_dir: Path | None = None,
) -> dict:
    """Detect each name, careers link or career host and record it in `profile/companies.json`. Never prints.

    A feed found is recorded as followed; a platform The other door cannot follow as ``unfollowable`` and a
    miss as ``unresolved``, both with the reason. An employer already followed is never unfollowed by
    a miss. With ``dry_run`` nothing is written.

    Returns:
        ``{"dry_run", "results": [{"input", "name", "status", "platform", "entry", "reason", "evidence",
        "candidates", "new"}]}``; ``new`` is False for an employer already on the list.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    items = store.load(profile_dir)
    now = store.now_iso()
    results = []
    location = str(common._load_config_or_defaults(profile_dir).get("location") or "")
    for found in _resolve_core(inputs, probe=probe, location=location)["results"]:
        name = _name_for(found)
        refusal = None
        if found["entry"]:
            status, reason = "followed", None
        elif found["platform"]:
            status, reason, refusal = "unfollowable", found["evidence"], found.get("refusal")
        else:
            tried = f" (tried {', '.join(found['candidates'])})" if found.get("candidates") else ""
            status, reason = "unresolved", "; ".join(found.get("notes") or []) or f"no job feed found{tried}"
        feed = (found["platform"], found["entry"]) if status == "followed" else None
        existing = store.find(items, name)
        was_dormant = existing is not None and existing.status == "dormant"
        if was_dormant and existing.feed is not None and not found["entry"]:
            # a dormant employer keeps its feed: adding it by hand follows it again on that feed
            status, reason, feed = "followed", None, (existing.feed.platform, existing.feed.id)
            found = {**found, "evidence": found.get("evidence") or "followed again by hand"}
        if dry_run:
            scratch = [store.Company.model_validate(c.model_dump()) for c in items]
            company, is_new = store.record(scratch, name, feed=feed, status=status, reason=reason,
                                           found_via="manual", evidence=found.get("evidence"), now=now, refusal=refusal)
        else:
            company, is_new = store.record(items, name, feed=feed, status=status, reason=reason,
                                           found_via="manual", evidence=found.get("evidence"), now=now, refusal=refusal)
        if company.found_via != "manual" and status == "followed" and was_dormant and not dry_run:
            company.found_via = "manual"  # kept by hand from now on: never retired
        results.append({"input": found["input"], "name": company.name, "status": company.status,
                        "platform": company.feed.platform if company.feed else found["platform"],
                        "entry": company.feed.id if company.feed else None, "reason": company.reason or reason,
                        "refusal": company.refusal, "evidence": found.get("evidence"), "candidates": found.get("candidates", []), "new": is_new})
    if not dry_run:
        store.save(profile_dir, items)
    return {"dry_run": dry_run, "results": results}


def _company_row(company: "store.Company") -> dict:
    return company.model_dump(mode="json")


def _list_core(
    *, status: str | None = None, found_via: str | None = None, profile_dir: Path | None = None,
) -> dict:
    """The employer list, optionally filtered. Never prints.

    Returns:
        ``{"companies": [{"name", "feed", "status", "reason", "found_via", "evidence", "first_seen",
        "last_checked"}], "counts": {status: n}}`` (counts over the whole list).

    Raises:
        ValueError: an unknown ``status`` or ``found_via``.
        CompaniesError: companies.json is invalid.
    """
    if status is not None and status not in store.STATUSES:
        raise ValueError(f"unknown status {status!r} (one of {', '.join(store.STATUSES)})")
    if found_via is not None and found_via not in store.found_via_values():
        raise ValueError(f"unknown found-via {found_via!r} (one of {', '.join(store.found_via_values())})")
    items = store.load(profile_dir if profile_dir is not None else workspace.PROFILE_DIR)
    shown = [c for c in items if (status is None or c.status == status) and (found_via is None or c.found_via == found_via)]
    return {"companies": [_company_row(c) for c in shown],
            "counts": {s: sum(1 for c in items if c.status == s) for s in store.STATUSES}}


@common._locked("companies remove")
def _remove_core(names: list[str], *, profile_dir: Path | None = None, jobs_dir: Path | None = None) -> dict:
    """Unfollow: remove each named employer from the list. Never prints.

    Returns:
        ``{"removed": [{"name", "feed"}], "not_found": [name, ...]}``.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    items = store.load(profile_dir)
    removed: list[dict] = []
    missing: list[str] = []
    for name in names:
        gone = store.remove(items, name)
        removed += [{"name": c.name, "feed": c.feed.model_dump() if c.feed else None} for c in gone]
        if not gone:
            missing.append(name)
    if removed:
        store.save(profile_dir, items)
    return {"removed": removed, "not_found": missing}


@common._locked("companies merge")
def _merge_core(names: list[str] | None = None, *, profile_dir: Path | None = None, jobs_dir: Path | None = None) -> dict:
    """Propose or make a merge of two entries that are one employer. Never prints.

    With no *names*, nothing is written: the groups of entries that share a feed or a name
    (`store.merge_candidates`). With two names, the second is folded into the first
    (`store.merge`) and the list saved; the user confirms each merge, nothing merges by itself.

    Returns:
        ``{"candidates": [{"names": [...], "reason": "same feed" | "same name"}]}``, or
        ``{"merged": <the surviving entry>, "removed": <the name folded in>}``.

    Raises:
        ValueError: exactly one name was given.
        CompaniesError: a name is not on the list, they are the same employer, or both are followed on different feeds.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    items = store.load(profile_dir)
    if not names:
        return {"candidates": store.merge_candidates(items)}
    if len(names) != 2:
        raise ValueError("merge takes two names (the employer to keep, then the one to fold into it), or none to list the duplicates")
    first, second = names
    removed = store.find_exact(items, second)
    merged = store.merge(items, first, second)
    store.save(profile_dir, items)
    return {"merged": _company_row(merged), "removed": removed.name if removed else second}


def _why_core(name: str, *, profile_dir: Path | None = None, jobs_dir: Path | None = None) -> dict:
    """Everything known about one employer. Never prints.

    Returns:
        ``{"company": {...the list entry...}, "postings": n, "by_source": {site: n}}`` — the postings
        in `jobs/` whose company is this one (same name, ignoring case and company suffixes).

    Raises:
        LookupError: no employer of that name on the list.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    company = store.find(store.load(profile_dir), name)
    if company is None:
        raise LookupError(f"no employer named {name!r} on the list; `./door companies` shows it")
    keys = {store.name_key(n) for n in (company.name, *company.aliases)}
    by_source: dict[str, int] = {}
    for file in sorted(workspace.postings_dir(jobs_dir).glob("*/*/*.json")):
        try:
            posting = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(posting, dict) and (posting.get("employer") == company.name
                                          or store.name_key(str(posting.get("company") or "")) in keys):
            source = str(posting.get("source") or file.parent.name)
            by_source[source] = by_source.get(source, 0) + 1
    return {"company": _company_row(company), "postings": sum(by_source.values()), "by_source": dict(sorted(by_source.items()))}


def _found_via(company: dict) -> str:
    """Where an employer was seen: ``company["via"]`` when given (the source that queued it), else the
    first of its postings' sources that `found_via` knows."""
    return company.get("via") or next((x for x in sorted(company["sources"]) if x in store.found_via_values() and x != "manual"), "manual")


def _classify(
    session: PoliteSession | None, company: dict, followed: set[tuple[str, str]], ctx=None,
) -> tuple[str, dict] | None:
    """What one company's links (and, with a session, its pages and name) show.

    *company* is ``{"company", "links", "postings", "sources"}`` (and ``"titles"``, the job titles queued
    for it). Returns ``("suggestions", item)``, ``("unfollowable", item)`` or ``("unresolved", item)`` for the
    result list of that name, or None when nothing is to be said (already followed, or no
    external link and no platform found). *ctx* (a `Context`) caches HR-Manager lookups across companies.
    """
    ctx = ctx if ctx is not None else Context()
    links = [_expand_short(session, l) for l in company["links"]] if session is not None else list(company["links"])
    external = [l for l in links if not ats_detect.is_job_board(l)]
    found_at = [(d, l) for l in links for d in [ats_detect.from_url(l)] if d is not None]
    dets = [d for d, _ in found_at]
    notes: list[str] = []
    confirm = _name_check(company, ctx)
    if session is not None:
        dets = [d for d in (_confirm(session, _look_through(session, d, l)) for d, l in found_at) if d is not None]
        if not any(d.entry for d in dets):
            for link in links:
                cid = hr_manager.hr_manager_cid(link)
                det = _hr_by_cid(session, link, cid, ctx) if cid else None
                if det is not None:
                    dets.insert(0, det)
                    break
        if not any(d.entry for d in dets):
            dets += [d for d in (_confirm(session, _detect_link(session, l)) for l in external[:1]) if d is not None]
    best = next((d for d in dets if d.entry), None) or next(iter(dets), None)
    if session is not None and best is not None and best.entry is None and (best.employer or best.site):
        best = _by_employer(session, best, confirm, notes, ctx) or best   # a look-through named the employer
    # No platform from the links: try the name, unless every posting already came from a followed feed.
    if (session is not None and (best is None or (best.entry is None and best.platform == "hr_manager"))
            and company["sources"] - set(sites.FEED_SITES)):
        cid = next((c for c in (hr_manager.hr_manager_cid(l) for l in links) if c), None)
        found = (hr_manager.alias_by_name(session, company["company"], cid, confirm) if best is not None else None) \
            or _probe_name(session, company["company"], confirm, notes, ctx.hosts, ctx.jobs)
        best = found or best
    if (session is not None and ctx.employers is not None and company["sources"] - set(sites.FEED_SITES)
            and (best is None or (best.entry is None and best.platform == "hr_manager"))):
        best = _by_website(session, company["company"], notes, ctx) or best   # the employer's own website (#566)
    if (session is not None and ctx.ai is not None and company["sources"] - set(sites.FEED_SITES)
            and (best is None or (best.entry is None and best.platform == "hr_manager"))):
        cid = next((c for c in (hr_manager.hr_manager_cid(l) for l in links) if c), None)
        best = _ask_ai(session, company, ctx, cid) or best
    dead = _dead_feed(session, best)
    if dead is not None:
        best, notes = None, [*notes, dead]
    via = _found_via(company)
    if best is None:
        if notes:
            item = {"company": company["company"], "links": external, "found_via": via, "reason": "; ".join(notes)}
            if any(wikidata.is_unasked(n) for n in notes):
                item["retry"] = True   # Wikidata was not asked (stopped, budget spent): ask again on a later run
            return "unresolved", item
        return ("unresolved", {"company": company["company"], "links": external, "found_via": via}) if external else None
    if best.entry is None and best.platform == "hr_manager":  # followable, but no customer alias was found
        return "unresolved", {"company": company["company"], "links": external, "found_via": via, "reason": best.evidence}
    if best.entry is None:
        return "unfollowable", {"company": company["company"], "platform": best.platform, "evidence": best.evidence,
                                "refusal": best.refusal, "found_via": via}
    if (best.config_key, best.entry.lower()) in followed:
        return None
    return "suggestions", {"company": company["company"], "platform": best.platform, "entry": best.entry,
                           "config_key": best.config_key, "evidence": best.evidence, "postings": company["postings"],
                           "found_via": via}


def _name_check(company: dict, ctx: Context) -> Callable[[list], str | None] | None:
    """The check a feed found by the employer's name alone must pass: a queued job title is among its
    jobs, or one is in the profile's place (`_name_confirm`); a demo account never passes (`_probe_name`)."""
    return _name_confirm(list(company.get("titles") or []), list(ctx.places))


def _ask_ai(session: PoliteSession, company: dict, ctx: Context, cid: str | None) -> ats_detect.Detection | None:
    """The last resort: the careers URL the model finds (`ctx.ai`) is fed back into the same checks, and
    only a confirmed feed is followed."""
    try:
        url = ctx.ai(company)
    except Exception:  # noqa: BLE001 - a failed question is no answer; the employer stays unresolved
        return None
    if not url:
        return None
    det = _detect_link(session, url)
    det = _confirm(session, det) if det is not None else None
    if det is None or det.entry is None:
        return None
    if det.platform == "hr_manager" and cid and not hr_manager.feed_has_cid(session, det.entry, cid):
        return None
    return replace(det, evidence=f"ai: {url} → {det.evidence}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
_MARKS = {"followed": click.style("✓", fg="green"), "unfollowable": click.style("✗", fg="red"),
          "unresolved": click.style("?", fg="yellow"), "dormant": click.style("·", dim=True)}


_REFUSALS = {"must_not": "won't follow", "cant_yet": "can't yet"}


def _feed_label(feed: dict | None) -> str:
    return f"{feed['platform']}:{feed['id']}" if feed else ""


def _company_line(company: dict) -> str:
    """``✓ BEC  hr_manager:bec  manual`` / ``✗ Danske Bank  jobindex  Oracle Cloud HCM: ...``."""
    parts = [f"{_MARKS[company['status']]} {company['name']}"]
    if company["feed"]:
        parts.append(_feed_label(company["feed"]))
    parts.append(company["found_via"])
    if company.get("aliases"):
        parts.append("aka: " + ", ".join(company["aliases"]))
    if company["status"] != "followed" and company.get("reason"):
        parts.append(f"({_REFUSALS[company['refusal']]}) {company['reason']}" if company.get("refusal") else company["reason"])
    problem = company.get("collect_problem")
    if problem:
        parts.append(f"{problem['outcome']}: {problem['reason']}")
    return "  ".join(parts)


@click.group("companies", invoke_without_command=True)
@click.pass_context
def companies_group(ctx: click.Context):
    """The employers The other door follows (profile/companies.json).

    `companies` lists them; `why`, `add`, `remove` and `merge` explain and change the list."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_companies, status=None, found_via=None)


def _fail(exc: Exception) -> None:
    click.echo(f"Error: {exc}", err=True)
    sys.exit(1)


@click.command("list")
@click.option("--status", type=click.Choice(store.STATUSES), default=None, help="Only employers with this status.")
@click.option("--found-via", "found_via", type=click.Choice(store.found_via_values()), default=None,
              help="Only employers found this way.")
def list_companies(status: str | None, found_via: str | None):
    """One line per employer: ✓ followed, ✗ unfollowable, ? unresolved, · dormant (no relevant job lately)."""
    try:
        result = _list_core(status=status, found_via=found_via, profile_dir=workspace.PROFILE_DIR)
    except (store.CompaniesError, ValueError) as exc:
        _fail(exc)
    if not result["companies"]:
        click.echo("No employers" + (" match." if status or found_via else " yet. `./door companies add <name or link>` follows one."))
        return
    for company in result["companies"]:
        click.echo(_company_line(company))
    counts = result["counts"]
    click.echo(f"{counts['followed']} followed, {counts['unfollowable']} unfollowable, {counts['unresolved']} unresolved"
               + (f", {counts['dormant']} dormant" if counts.get("dormant") else ""))


@click.command("add")
@click.argument("inputs", nargs=-1, required=True)
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Show what would be recorded; write nothing.")
@click.option("--probe/--no-probe", default=True, show_default=True,
              help="Probe each feed's public endpoint for a bare name (and read careers pages).")
def add_company(inputs: tuple[str, ...], dry_run: bool, probe: bool):
    """Follow the employers named by INPUTS (company names, careers links or career hosts)."""
    try:
        result = _add_core(list(inputs), dry_run=dry_run, probe=probe, profile_dir=workspace.PROFILE_DIR,
                           jobs_dir=workspace.JOBS_DIR)
    except (store.CompaniesError, ValueError) as exc:
        _fail(exc)
    verb = "Would record" if dry_run else "Recorded"
    for item in result["results"]:
        mark = _MARKS[item["status"]]
        if item["status"] == "followed":
            click.echo(f"{mark} {item['name']}: {item['platform']}:{item['entry']}")
            click.echo(f"  {item['evidence']}")
        else:
            kind = f" ({_REFUSALS[item['refusal']]})" if item.get("refusal") else ""
            click.echo(f"{mark} {item['name']}: {item['status']}{kind}")
            click.echo(f"  {item['reason']}")
    if dry_run and result["results"]:
        click.echo(f"{verb} nothing (--dry-run).")


@click.command("remove")
@click.argument("names", nargs=-1, required=True)
def remove_company(names: tuple[str, ...]):
    """Stop following the named employers (removes them from the list)."""
    try:
        result = _remove_core(list(names), profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)
    except store.CompaniesError as exc:
        _fail(exc)
    for item in result["removed"]:
        click.echo(f"Removed {item['name']}.")
    for name in result["not_found"]:
        click.echo(f"{name}: not on the list.", err=True)
    if result["not_found"] and not result["removed"]:
        sys.exit(1)


@click.command("merge")
@click.argument("names", nargs=-1)
def merge_companies(names: tuple[str, ...]):
    """Merge two entries that are one employer: NAMES are the one to keep, then the one folded into it.

    With no names, lists the entries that share a feed or a name (nothing is merged)."""
    if len(names) == 1:
        raise click.UsageError("give two names (the employer to keep, then the one to fold into it), or none to list the duplicates")
    try:
        result = _merge_core(list(names), profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)
    except (store.CompaniesError, ValueError) as exc:
        _fail(exc)
    if "candidates" in result:
        if not result["candidates"]:
            click.echo("No duplicate employers.")
            return
        for group in result["candidates"]:
            click.echo(f"{', '.join(group['names'])}  ({group['reason']})")
        click.echo("Merge one with `./door companies merge <keep> <fold in>`.")
        return
    click.echo(f"Merged {result['removed']} into {result['merged']['name']}.")


@click.command("why")
@click.argument("name")
def why_company(name: str):
    """Everything known about one employer: feed, status, evidence, dates and postings."""
    try:
        result = _why_core(name, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)
    except (store.CompaniesError, LookupError) as exc:
        _fail(exc)
    company = result["company"]
    click.echo(_company_line(company))
    click.echo(f"  status:       {company['status']}")
    if company.get("aliases"):
        click.echo(f"  aliases:      {', '.join(company['aliases'])}")
    click.echo(f"  feed:         {_feed_label(company['feed']) or 'none'}")
    if company.get("refusal"):
        click.echo(f"  refusal:      {_REFUSALS[company['refusal']]}")
    if company.get("reason"):
        click.echo(f"  reason:       {company['reason']}")
    if company.get("evidence"):
        click.echo(f"  evidence:     {company['evidence']}")
    click.echo(f"  found via:    {company['found_via']}")
    click.echo(f"  first seen:   {company.get('first_seen') or 'unknown'}")
    click.echo(f"  last checked: {company.get('last_checked') or 'unknown'}")
    click.echo(f"  last relevant: {company.get('last_relevant') or 'never'}")
    if company.get("collect_problem"):
        problem = company["collect_problem"]
        click.echo(f"  collect:      {problem['outcome']} on {problem['at']}: {problem['reason']}")
    if company["status"] == "dormant":
        click.echo("  dormant: not collected until a fitting job is seen again (search or discover follows it "
                   "again) or `companies add` follows it again.")
    sources = ", ".join(f"{site} {n}" for site, n in result["by_source"].items())
    click.echo(f"  postings:     {result['postings']}" + (f" ({sources})" if sources else ""))
