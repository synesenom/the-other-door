"""Which job feed a company's careers link, DNS name or careers page belongs to (issue #233, #282).

Each feed platform's module owns what it knows about itself (`detect_url`, `detect_cname`,
`detect_html`, `feed_url`, `name_probes`; see `door.scrapers.sdk`); this module is the dispatcher
that asks them in `PRECEDENCE` order, plus the helpers that belong to no platform. Pure: every
function reads a URL, a CNAME or an HTML string the caller fetched.
A `Detection` names the platform and, when The other door can follow it, the entry for
that feed (the id in `profile/companies.json`); a platform The other door knows but cannot follow
(its terms or robots.txt rule it out, or the link names no account) comes back
with ``entry=None`` and the reason in ``evidence``.
"""

import importlib
import re
import unicodedata
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from door import i18n
from door.core import sites

# The modules under `door.scrapers.feeds` that detect a platform, in the order they are asked: the order
# a careers page's links to several platforms are weighed in, and the order a company name is probed
# in. The one place the dispatcher names platforms.
PRECEDENCE = (
    "greenhouse", "lever", "ashby", "recruitee", "pinpoint", "teamtailor", "jobylon", "workable", "hr_manager", "hr_on", "visma_recruit",
    "successfactors", "emply", "recman", "beetween", "digitalrecruiters", "jobtrain", "networx", "eploy", "icims", "career_sites", "oracle_hcm", "phenom", "smartrecruiters", "signatur", "dayforce", "varbi",
    "reachmee", "ponty", "flatchr", "talentsoft", "personio", "taleez", "welcometothejungle", "jobaffinity",
)

NOT_ACCOUNTS = {"www", "app", "career", "careers", "assets", "api", "secure", "j", "embed", "jobs"}


@dataclass(frozen=True)
class Detection:
    platform: str
    entry: str | None
    evidence: str
    refusal: str | None = None   # why no entry: "must_not" (terms or robots rule it out) or "cant_yet" (no way in yet)
    employer: str | None = None  # a look-through's find: the employer's own name, for `follow` to try by name (#526)
    site: str | None = None      # ... and its own website, for `follow` to read for the platform it uses

    @property
    def config_key(self) -> str | None:
        """The key the platform's scraper reads its entries under (`sites.FEED_SITES`)."""
        return sites.FEED_SITES.get(self.platform) if self.entry else None


def safe_urlparse(url: str):
    """`urlparse`, but a malformed URL (``http://[bad``) parses as an empty one instead of raising."""
    try:
        return urlparse(url)
    except ValueError:
        return urlparse("")


def parts(url: str) -> tuple[str, list[str], dict[str, str]]:
    parsed = safe_urlparse(url if "://" in url else f"https://{url}")
    query = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
    return parsed.netloc.lower().split(":")[0], [p for p in parsed.path.split("/") if p], query


def first(path: list[str]) -> str | None:
    return path[0].lower() if path and path[0].lower() not in NOT_ACCOUNTS else None


def _modules(hook: str | None = None):
    """The platform modules in `PRECEDENCE` order (only those with *hook*, when given). Imported
    at call time: the modules import the SDK, which imports this one."""
    mods = [importlib.import_module(f"door.scrapers.feeds.{name}") for name in PRECEDENCE]
    return [m for m in mods if hook is None or hasattr(m, hook)]


def from_url(url: str) -> Detection | None:
    """The platform a careers or job link is on, with the feed entry it names."""
    if not url or " " in url.strip() or "." not in url:
        return None
    try:
        for module in _modules("detect_url"):
            det = module.detect_url(url)
            if det is not None:
                return det
    except ValueError:  # a malformed link (``http://[bad``) is no detection
        return None
    return None


def follow_link(session, url: str) -> Detection | None:
    """The detection for a link found inside another platform's pages (a front end's apply link), from the first
    platform module whose ``follow_link(session, url)`` recognises it: an entry when that system's public job
    list is not empty, else an entry-less detection saying why not. Reads the network through *session*."""
    for module in _modules("follow_link"):
        det = module.follow_link(session, url)
        if det is not None:
            return det
    return None


def from_cname(host: str, cname: str) -> Detection | None:
    """The platform a career host points at through its DNS CNAME."""
    target = (cname or "").lower().rstrip(".")
    where = f"{host} is a CNAME for {target}"
    for module in _modules("detect_cname"):
        det = module.detect_cname(host, target, where)
        if det is not None:
            return det
    return None


_URL_IN_HTML = re.compile(r"""https?://(?:(?!&quot;|&#34;|&#x22;)[^\s"'<>\\)])+""")


def from_html(html: str, url: str) -> Detection | None:
    """The platform a careers page embeds or links to, else what its markup shows."""
    found: dict[str, Detection] = {}
    for link in _URL_IN_HTML.findall(html or ""):
        det = from_url(link.rstrip(".,;"))
        if det is not None and (det.platform not in found or (det.entry and not found[det.platform].entry)):
            found[det.platform] = det
    for module in _modules("detect_url"):
        for platform in getattr(module, "LINK_PLATFORMS", (module.__name__.rsplit(".", 1)[-1],)):
            if platform in found:
                det = found[platform]
                if det.entry is None and hasattr(module, "detect_html"):  # a link that names no entry: the page may
                    det = module.detect_html(html or "", url) or det      # name it another way (a scheme-less link)
                    return det if det.entry else replace(det, evidence=f"{url} links to it: {det.evidence}")
                return replace(det, evidence=f"{url} links to it: {det.evidence}")
    for module in _modules("detect_html"):
        det = module.detect_html(html or "", url)
        if det is not None:
            return det
    return None


def name_probes(slugs: list[str]) -> list[tuple]:
    """``(platform, slug, probe)`` for each public feed endpoint to try for a company name's *slugs*:
    platform by platform in `PRECEDENCE` order, and within a platform each of its probes over all the slugs
    before its next probe (a platform with two hosts tries both hosts for every slug in turn)."""
    out = []
    for module in _modules("name_probes"):
        platform = module.__name__.rsplit(".", 1)[-1]
        per_slug = [(slug, module.name_probes(slug)) for slug in slugs]
        for i in range(max((len(p) for _, p in per_slug), default=0)):
            out += [(platform, slug, probes[i]) for slug, probes in per_slug if i < len(probes)]
    return out


def tenant_probes() -> list:
    """Each platform's ``tenant_probe(session, slug) -> Detection | None``, in `PRECEDENCE` order: the tenant a
    known employer's own name may have on the platform, tried only for an employer whose website was found (#566)."""
    return [module.tenant_probe for module in _modules("tenant_probe")]


def _spellings(text: str) -> list[str]:
    """*text* in lower-case ASCII: its special letters spelled out (``ø`` -> ``oe``), then reduced
    to their look-alike (``ø`` -> ``o``, an accent dropped: ``ö`` -> ``o``)."""
    return i18n.slug_spellings(text.strip())


def _suffixes() -> set[str]:
    """Words around a name that are no part of its slug: every country's legal forms and names, and the
    international ones (`i18n`)."""
    words = list(i18n.slug_suffixes())
    for country in i18n.countries().values():
        words += [country.name, *country.names]
    return {w for phrase in words for form in _spellings(phrase) for w in re.split(r"[^a-z0-9/]+", form) if w}


def slug_candidates(name: str) -> list[str]:
    """The slugs a company's name most likely has on a job board: joined and hyphenated, for each
    spelling of its special letters. Legal forms and country names drop out ("Novo Nordisk A/S",
    "Wizz Air Hungary Zrt."). (Not its first word alone: "novo" is somebody else's board.)"""
    suffixes = _suffixes()
    out: list[str] = []
    for text in _spellings(name):
        words = [w for w in re.split(r"[^a-z0-9/]+", text) if w and w not in suffixes]
        words = [w.replace("/", "") for w in words if w.replace("/", "")]
        if words:
            out += ["".join(words), "-".join(words)]
    return list(dict.fromkeys(out))


# Boards, aggregators and recruiters: a link on one says nothing about where an
# employer's own ads live, so none of them is ever read as a career site (#256).
_JOB_BOARD_HOSTS = (
    "linkedin.", "indeed.", "jobunivers.", "job.experis.", "experis.", "carbontalent", "glassdoor.", "monster.", "stepstone.",
    "jooble.", "talent.com", "careerjet.", "ziprecruiter.", "adzuna.", "jobbank.", "jobsdb.",
)
# A platform or board module adds its own: `JOB_BOARD_HOSTS` (markers in a host), `JOB_BOARD_EXACT` (whole hosts).


# Whole domains (the host or any subdomain of it) and single hosts: job boards, aggregators and
# recruiters whose pages carry JobPosting markup yet are never an employer's own career site.
_JOB_BOARD_DOMAINS = (
    "join.com", "jobylon.com", "engradar.com", "jobmatchprofile.com",
)  # (a country's own boards are in its `i18n/country/<cc>.toml` `job_boards`)
_JOB_BOARD_EXACT = ("apply.careers.microsoft.com",)


# Career platforms The other door has no module for, whose customers' sites live on subdomains of these
# (``dca.career.emply.com``); each platform module lists its own in `PLATFORM_DOMAINS`.
_PLATFORM_DOMAINS = ("hr-skyen.dk", "jobteaser.com", "bamboohr.com")


def platform_domains() -> tuple[str, ...]:
    """The domains of the career platforms The other door knows: a host on one belongs to a customer of the
    platform, so its registrable label (``emply``, ``myworkdayjobs``) never names an employer (#436)."""
    found = (d for m in _modules("PLATFORM_DOMAINS") for d in m.PLATFORM_DOMAINS)
    return tuple(dict.fromkeys((*found, *_PLATFORM_DOMAINS)))


def platform_domain_of(host: str) -> str | None:
    """The platform domain *host* is on (itself or a subdomain), or None."""
    host = host.lower().split(":")[0]
    return next((d for d in platform_domains() if host == d or host.endswith("." + d)), None)


def is_job_board(url: str) -> bool:
    """Whether *url* is on a job board, aggregator or recruiter rather than an employer's own site."""
    host = safe_urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    from door.core import discovery_sources

    boards = [importlib.import_module(s.module) for s in sites.SITES.values() if s.board]
    sources = [discovery_sources.get(name) for name in discovery_sources.SOURCES]
    modules = [*_modules(), *boards, *sources]
    markers = _JOB_BOARD_HOSTS + tuple(h for m in modules for h in getattr(m, "JOB_BOARD_HOSTS", ()))
    exact = _JOB_BOARD_EXACT + tuple(h for m in modules for h in getattr(m, "JOB_BOARD_EXACT", ()))
    return (any(marker in host for marker in markers) or host in exact
            or any(host == d or host.endswith("." + d) for d in (*_JOB_BOARD_DOMAINS, *i18n.job_board_domains())))


def is_shared_ats_host(url: str) -> bool:
    """Whether *url* is on an ATS host shared by many employers (no career site of its own): a host whose
    ad pages hold nothing that leads to the employer's own list (a platform module's `is_shared_host`)."""
    host = safe_urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    return any(m.is_shared_host(host) for m in _modules("is_shared_host"))


def is_short_link(url: str) -> bool:
    """Whether *url* is a short link that redirects to the real page (Talentech's ``go.talentech.io``)."""
    return safe_urlparse(url if "://" in url else f"https://{url}").netloc.lower() == "go.talentech.io"


def unwrap_redirect(url: str) -> str | None:
    """The page a Talentech redirect URL (``careersites-api.talentech.io/redirect?original_apply_url=...``)
    points at, else None."""
    parsed = safe_urlparse(url)
    if parsed.netloc.lower() != "careersites-api.talentech.io":
        return None
    target = parse_qs(parsed.query).get("original_apply_url")
    return target[0] if target else None


# --------------------------------------------------------------------------- #
# Careers links: where an employer's home page points to its job system
# --------------------------------------------------------------------------- #

# Social sites: they have "jobs" tabs but are not the employer's job system.
_SOCIAL = ("facebook.", "instagram.", "twitter.", "x.com", "youtube.", "tiktok.", "xing.", "github.")
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".doc", ".docx")
_SECOND_LEVEL = {"co", "com", "org", "ac", "gov", "net"}


def _site(host: str) -> str:
    labels = host.split(":")[0].split(".")
    keep = 3 if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


def career_links(html: str, base_url: str, limit: int = 6) -> list[str]:
    """The page's links that look like a careers/jobs page, absolute and deduplicated.

    A link counts when its anchor text or its address (host and path, "-" "_" "/"
    read as spaces) holds a careers word from the language data (`i18n`:
    "careers", "karriere", "ledige stillinger", ...). Job boards, social sites,
    mailto/javascript links and files are left out. Best first: anchor-text
    matches before address-only ones, and within each the employer's own site
    (a `careers.`-style subdomain first) before other sites; ties keep page order.
    """
    pattern = i18n.compile_words(i18n.career_words())
    base_host = safe_urlparse(base_url).netloc.lower()
    base_site = _site(base_host)
    scored: dict[str, tuple[int, int, int, int]] = {}
    for order, a in enumerate(BeautifulSoup(html or "", "html.parser").find_all("a", href=True)):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            url = urldefrag(urljoin(base_url, href))[0]
            parsed = urlparse(url)
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https") or is_job_board(url) or any(s in parsed.netloc.lower() for s in _SOCIAL) or parsed.path.lower().endswith(_SKIP_EXT):
            continue
        if url.rstrip("/") == base_url.split("#")[0].rstrip("/"):
            continue
        host = parsed.netloc.lower()
        address = re.sub(r"[-_/.+]+", " ", host.removeprefix("www.") + parsed.path)
        in_text = bool(pattern.search(a.get_text(" ", strip=True)))
        if not in_text and not pattern.search(address):
            continue
        own = 0 if _site(host) == base_site else 1
        careers_host = 0 if host != base_host and pattern.search(host.split(".")[0]) else 1
        key = (0 if in_text else 1, own, careers_host, order)
        if url not in scored or key < scored[url]:
            scored[url] = key
    return sorted(scored, key=scored.get)[:limit]


# --------------------------------------------------------------------------- #
# A listing page whose ads are plain links (a career site without sitemap or markup)
# --------------------------------------------------------------------------- #

_MIN_ADS = 3   # a listing with fewer ad links is believed only when the link that led there is one of them


def _segments(path: str) -> list[str]:
    return [s.lower() for s in path.split("/") if s]


def _query(url: str) -> dict[str, str]:
    return {k.lower(): v[0] for k, v in parse_qs(safe_urlparse(url).query).items()}


def _plain(text: str) -> str:
    return re.sub(r"[\s_-]+", " ", text).strip().lower()


def _ad_key(url: str) -> tuple[str, tuple]:
    """A job link without tracking parameters: its path and the parameters that carry the job's id."""
    ids = set(i18n.job_id_params()) | {"id"}
    return (safe_urlparse(url).path.lower().rstrip("/"), tuple(sorted((k, v) for k, v in _query(url).items() if k in ids)))


def ad_links(html: str, page_url: str, limit: int = 300) -> list[str]:
    """The links of a careers listing page that lead to one job ad, absolute and in page order.

    A link on the employer's own site counts when it sits below the listing (a child path), or
    beside it with a job word in its path (``JobList.aspx`` -> ``JobDetails.aspx``), or is the same
    page with a job id in its query; it must not contradict the listing's own query (a client id).
    A link on a shared ATS host counts when it carries a job id (``career_job_req_id``). Links whose
    text is navigation ("all jobs", "next"), pages, files and social sites are left out. A listing at
    the site root only gives links whose path holds a job word. Pure."""
    base = urldefrag(page_url)[0]
    bp = safe_urlparse(base)
    bsegs, bq = _segments(bp.path), _query(base)
    stems = [s.lower() for s in i18n.career_path_stems()]
    nav = {_plain(w) for w in i18n.career_nav_words()}
    ids = set(i18n.job_id_params())
    found: dict[str, None] = {}
    for a in BeautifulSoup(html or "", "html.parser").find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            url = urldefrag(urljoin(base, href))[0]
            p = urlparse(url)
        except ValueError:
            continue
        if p.scheme not in ("http", "https") or p.path.lower().endswith(_SKIP_EXT) or is_job_board(url):
            continue
        if any(s in p.netloc.lower() for s in _SOCIAL) or url.rstrip("/") == base.rstrip("/"):
            continue
        segs, q = _segments(p.path), _query(url)
        text = _plain(a.get_text(" ", strip=True))
        if text in nav or (segs and _plain(segs[-1]) in nav) or (segs and segs[-2:-1] == ["page"]) or (segs and segs[-1] == "page"):
            continue
        has_stem = bool(segs) and any(s in segs[-1] for s in stems)
        if _site(p.netloc.lower()) != _site(bp.netloc.lower()):
            if not (is_shared_ats_host(url) and ids & q.keys()):
                continue
        else:
            if any(k in bq and bq[k] != v for k, v in q.items()):
                continue
            below = bool(bsegs) and len(segs) > len(bsegs) and segs[:len(bsegs)] == bsegs
            beside = bool(bsegs) and segs[:-1] == bsegs[:-1] and segs != bsegs and has_stem
            same_page = segs == bsegs and bool(ids & q.keys() or "id" in q) and q != bq
            at_root = not bsegs and any(s in seg for seg in segs for s in stems)
            if not (below or beside or same_page or at_root):
                continue
        found.setdefault(url)
        if len(found) >= limit:
            break
    return list(found)


def listing_detection(html: str, page_url: str, hint: str | None = None) -> Detection | None:
    """A career site read through its listing page: ``career_sites`` with *page_url* as the entry,
    when the page links at least `_MIN_ADS` job ads, or one of them is *hint* (the ad link that led
    to this page); a home page only counts for the hint. Pure."""
    links = ad_links(html, page_url)
    led_here = hint is not None and _ad_key(hint) in {_ad_key(l) for l in links}
    if not led_here and (len(links) < _MIN_ADS or not _segments(safe_urlparse(page_url).path)):
        return None  # a home page that links careers pages is a menu, not a listing
    url = urldefrag(page_url)[0]
    return Detection("career_sites", url, f"{url} links {len(links)} job ads (no sitemap or job markup needed)")


# --------------------------------------------------------------------------- #
# Is a feed found by an employer's name really that employer's?
# --------------------------------------------------------------------------- #

_TITLE_KEYS = ("title", "text", "name", "position", "jobtitle", "job_title")
_PLACE_KEYS = ("loc", "city", "country", "office", "address", "place", "region")


def places_for(location: str) -> list[str]:
    """The place names that say a job is where the profile looks: its location's parts and the names of
    its country (lower case); empty for no location. Pure."""
    parts = [p.strip().lower() for p in (location or "").split(",") if p.strip()]
    country = i18n.country_for_location(location or "")
    if country is not None:
        parts += [n.lower() for n in [country.name, *country.names]]
    return list(dict.fromkeys(parts))


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def _strings(node, keys: tuple[str, ...], *, under: bool = False):
    """The string values of a JSON structure whose key (or whose parent's key) contains one of *keys*."""
    if isinstance(node, str):
        if under:
            yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            hit = under or any(k in str(key).lower() for k in keys)
            yield from _strings(value, keys, under=hit)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value, keys, under=under)


def _item_titles(item) -> list[str]:
    if not isinstance(item, dict):
        return []
    return [_norm(v) for k, v in item.items() if str(k).lower() in _TITLE_KEYS and isinstance(v, str) and v.strip()]


def _title_matches(wanted: str, found: str) -> bool:
    """Equal, or one inside the other when the shorter has at least two words and eight letters."""
    if not wanted or not found:
        return False
    if wanted == found:
        return True
    short, long = sorted((wanted, found), key=len)
    return len(short.split()) >= 2 and len(short) >= 8 and re.search(rf"(?<![a-z0-9]){re.escape(short)}(?![a-z0-9])", long) is not None


def feed_looks_demo(items: list) -> str | None:
    """Why the jobs *items* look like a platform's demo or sample account rather than an employer's
    (a title marked "(Sample)", a "Copy of ..." title, placeholder text; `i18n/common.toml`), else None. Pure (#435)."""
    pack = i18n.common()
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if str(key).lower() in _TITLE_KEYS and isinstance(value, str):
                title = " ".join(value.lower().split())
                if any(m in title for m in pack.demo_title_marks) or title.startswith(tuple(pack.demo_title_prefixes)):
                    return f"a job titled {value.strip()!r}"
        text = " ".join(" ".join(_strings(item, ("",))).lower().split())
        mark = next((m for m in pack.demo_text_marks if m in text), None)
        if mark:
            return f"placeholder text ({mark!r})"
    return None


def feed_fingerprint(items: list) -> tuple[str, ...] | None:
    """The sorted job titles of a feed, to tell two accounts with the same jobs (a shared demo, #435); None
    for fewer than three jobs, too few to tell a demo from a coincidence. Pure."""
    titles = sorted(t for item in items for t in _item_titles(item)[:1])
    return tuple(titles) if len(titles) >= 3 else None


def feed_confirms(items: list, titles: list[str], places: list[str]) -> str | None:
    """Why the jobs *items* of a feed found by an employer's name belong to that employer, else None:
    one of the *titles* queued for it is among them, or one of them is in one of the *places*
    (looked for in location-like fields only). Pure."""
    wanted = [t for t in (_norm(x) for x in titles) if t]
    for item in items:
        for found in _item_titles(item):
            for title in wanted:
                if _title_matches(title, found):
                    return f"a queued job title ({title!r}) is in its feed"
    named = [p for p in (_norm(x) for x in places) if p]
    for item in items:
        text = _norm(" ".join(_strings(item, _PLACE_KEYS)))
        for place in named:
            if re.search(rf"(?<![a-z0-9]){re.escape(place)}(?![a-z0-9])", text):
                return f"its feed has a job in {place}"
    return None
