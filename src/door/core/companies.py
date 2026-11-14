"""The employer list: `profile/companies.json`, the single source of truth for followed employers.

Shape (``version`` 1)::

    {"version": 1, "companies": [
      {"name": "BEC Financial Technologies",
       "feed": {"platform": "hr_manager", "id": "bec"},          # null unless followed
       "status": "followed",                                    # | "unfollowable" | "unresolved" | "dormant"
       "reason": null,                                          # why it is not followed
       "found_via": "manual",                                   # | a board, a discovery source, "ai" (found_via_values())
       "evidence": "HR-Manager feed bec lists open jobs",
       "aliases": [],                                           # other names of the employer (formerly "also")
       "first_seen": "2026-01-02T03:04:05+00:00", "last_checked": "2026-01-02T03:04:05+00:00",
       "last_relevant": null}                                   # set by collect and match; see `retire_idle`
    ]}

A ``dormant`` employer was followed, yielded no relevant job for ``retire_after_days`` and is no longer
collected; it keeps its feed, and a fitting ad seen again (or `companies add`) follows it again.
``feed.platform`` is one of `sites.FEED_SITES`; ``feed.id`` is the entry that platform's
scraper reads (a board token, a slug, a customer alias, a career host). The name is a label
and a lookup handle (case- and suffix-insensitive, see `name_key`), not a unique key: a feed
is. Scrapers stay stateless: `feed_config` hands `_scrape_core` each platform's followed ids
under the key names the scrapers have always read.

The feeds are driven by this list, not by config keys: `Profile` accepts none of the per-platform
lists, and the job boards `search` reads are those of the profile's country (`sites.boards_for_location`).

Writes are atomic (`utils.write_json_atomic`). The file lives in `profile/`, which no
`jobs/` ledger lock covers; callers read-modify-write it in one go.
"""

import importlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from door import i18n
from door.core import ats_detect, migrations, sites, utils

FILENAME = "companies.json"
VERSION = 1
STATUSES = ("followed", "unfollowable", "unresolved", "dormant")
_FOUND_VIA_EXTRA = ("manual", "ai", "linkedin")   # not (or not only) a board: a person, the AI fallback, discovery sources

Status = Literal["followed", "unfollowable", "unresolved", "dormant"]


def found_via_values() -> tuple[str, ...]:
    """Every value ``found_via`` can take: ``manual``, ``ai``, each board in `sites.SITES` and each source in
    `discovery_sources.SOURCES`, read at call time so a new source needs no list edit here."""
    from door.core import discovery_sources
    names = list(_FOUND_VIA_EXTRA) + [s.name for s in sites.SITES.values() if s.board] + list(discovery_sources.SOURCES)
    return tuple(dict.fromkeys(names))


class CompaniesError(Exception):
    """`profile/companies.json` is malformed or fails validation (one line per problem in ``str``)."""


class Feed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    id: str

    @field_validator("platform")
    @classmethod
    def _known_platform(cls, v: str) -> str:
        if v not in sites.FEED_SITES:
            raise ValueError(f"unknown platform {v!r} (known: {', '.join(sites.FEED_SITES)})")
        return v

    @field_validator("id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("feed id is empty")
        return v.strip()


# Platforms a `career_sites` entry moves to when its host belongs to them (`Company._migrate_career_site_feed`).
_UPGRADED_PLATFORMS = ("emply",)


def _dedupe(names) -> list[str]:
    """*names* without repeats by `name_key` (first spelling kept, order kept); non-strings pass through."""
    seen: set[str] = set()
    out = []
    for n in names:
        key = name_key(n) if isinstance(n, str) else repr(n)
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


class CollectProblem(BaseModel):
    """Why the last `collect` could not read a followed employer's feed (#437): ``blocked`` (bot protection,
    a refusal) or ``failed`` (an error), when, and the scraper's message. `collect` stamps and clears it."""

    model_config = ConfigDict(extra="forbid")

    at: str
    outcome: Literal["blocked", "failed"]
    reason: str


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    feed: Feed | None = None
    status: Status
    reason: str | None = None
    found_via: str   # one of `found_via_values()`; an older file may hold a source that is gone, kept as written
    evidence: str | None = None
    aliases: list[str] = []       # other names of this employer (same feed, or merged in)
    first_seen: str | None = None
    last_checked: str | None = None
    refusal: Literal["must_not", "cant_yet"] | None = None   # unfollowable: its terms forbid it, or no way in yet (#438)
    collect_problem: CollectProblem | None = None   # the last collect could not read its feed (#437)
    last_relevant: str | None = None   # when a posting of this employer last fitted the keywords or cleared min_score

    @model_validator(mode="before")
    @classmethod
    def _migrate_career_site_feed(cls, data):
        """An employer followed as a `career_sites` host that a dedicated feed platform serves (an Emply
        career site, #437) moves to that platform: its ad pages carry no markup `career_sites` can read."""
        feed = data.get("feed") if isinstance(data, dict) else None
        if isinstance(feed, dict) and feed.get("platform") == "career_sites" and isinstance(feed.get("id"), str):
            det = ats_detect.from_url(feed["id"] if "://" in feed["id"] else f"https://{feed['id']}")
            if det is not None and det.platform in _UPGRADED_PLATFORMS and det.entry:
                data = {**data, "feed": {"platform": det.platform, "id": det.entry}}
        return data

    @model_validator(mode="before")
    @classmethod
    def _migrate_also(cls, data):
        """Entries written before #314 call the aliases ``also``; fold them into ``aliases``."""
        if isinstance(data, dict) and "also" in data:
            data = dict(data)
            old = data.pop("also")
            if isinstance(old, list) and isinstance(data.get("aliases", []), list):
                data["aliases"] = _dedupe([*data.get("aliases", []), *old])
        return data

    @field_validator("name")
    @classmethod
    def _named(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name is empty")
        return v.strip()

    @model_validator(mode="after")
    def _followed_has_a_feed(self) -> "Company":
        if self.status == "followed" and self.feed is None:
            raise ValueError("a followed company needs a feed")
        return self


def path(profile_dir: Path | None = None) -> Path:
    if profile_dir is None:
        from door.core import workspace

        profile_dir = workspace.PROFILE_DIR
    return Path(profile_dir) / FILENAME


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(profile_dir: Path | None = None) -> list[Company]:
    """The employer list; empty when the file does not exist.

    Raises:
        CompaniesError: the file is not valid JSON, has another version, or an entry is invalid.
    """
    file = path(profile_dir)
    if not file.exists():
        return []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompaniesError(f"{file}: invalid JSON — {exc}") from None
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("companies"), list):
        raise CompaniesError(f'{file}: expected {{"version": {VERSION}, "companies": [...]}} — '
                             "unsupported version or missing companies list")
    items, problems = [], []
    for index, raw in enumerate(data["companies"]):
        try:
            items.append(Company.model_validate(raw))
        except ValidationError as exc:
            for err in exc.errors():
                key = ".".join(["companies", str(index), *(str(p) for p in err["loc"])])
                problems.append(f"{file}: {key} — {err['msg'].removeprefix('Value error, ')}")
    if problems:
        raise CompaniesError("\n".join(problems))
    return items


def save(profile_dir: Path | None, items: list[Company]) -> None:
    """Write the list atomically."""
    payload = {"version": VERSION, "companies": [c.model_dump(mode="json") for c in items]}
    target = path(profile_dir)
    migrations.ensure_folder(target.parent, "profile")
    utils.write_json_atomic(target, payload)


# --------------------------------------------------------------------------- #
# Lookup and editing (pure, on a list the caller loaded)
# --------------------------------------------------------------------------- #

def name_key(name: str) -> str:
    """The lookup form of a name: lower case, transliterated, legal suffixes dropped ("Novo Nordisk A/S" ->
    "novonordisk")."""
    candidates = ats_detect.slug_candidates(name)
    return candidates[0] if candidates else name.strip().lower()


def _names(company: Company) -> list[str]:
    return [company.name, *company.aliases]


def find(items: list[Company], name: str) -> Company | None:
    """The employer named *name*, by its name or one of its aliases."""
    key = name_key(name)
    return next((c for c in items if any(name_key(n) == key for n in _names(c))), None)


def find_exact(items: list[Company], name: str) -> Company | None:
    """The entry whose own name is *name* (case-insensitive), else what `find` gives. Entries that share a
    `name_key` (the duplicates `merge` folds) can be told apart this way."""
    exact = name.strip().lower()
    return next((c for c in items if c.name.lower() == exact), None) or find(items, name)


def find_by_feed(items: list[Company], platform: str, entry: str) -> Company | None:
    return next((c for c in items if c.feed and c.feed.platform == platform and c.feed.id.lower() == entry.lower()), None)


def record(
    items: list[Company], name: str, *, feed: tuple[str, str] | None, status: str, found_via: str,
    reason: str | None = None, evidence: str | None = None, now: str | None = None, refusal: str | None = None,
) -> tuple[Company, bool]:
    """Add *name* to *items* or update its entry in place; returns ``(company, is_new)``.

    The existing entry is found by feed, else by name (or an alias) unless that entry is on another
    feed: two feeds are two entries, flagged by `merge_candidates`, never folded by a name alone (#436);
    a name found on an existing feed is added to that entry's aliases, not listed twice. It keeps ``first_seen`` and ``found_via``;
    a result that is not "followed" never unfollows a followed company (only ``last_checked``
    moves); a followed result replaces the feed, status and reason. A followed result on a feed that
    serves several employers (`shared_name`) is kept as one entry under the feed's own name, the agency
    that led to it in its ``evidence`` (`_record_shared`).
    """
    now = now or now_iso()
    if feed and status == "followed" and shared_name(*feed):
        return _record_shared(items, name, feed, found_via, evidence, now)
    new_feed = Feed(platform=feed[0], id=feed[1]) if feed else None
    existing = find_by_feed(items, *feed) if feed else None
    named = find(items, name)
    if existing is None and named is not None and not (new_feed and named.feed and not _same_feed(named.feed, new_feed)):
        existing = named  # (a name alone never folds a second feed into an entry: `merge_candidates` flags it, #436)
    if existing is None:
        company = Company(name=name, feed=new_feed, status=status, reason=reason, found_via=found_via,
                          evidence=evidence, first_seen=now, last_checked=now, refusal=refusal)
        items.append(company)
        return company, True
    existing.last_checked = now
    if new_feed and existing.feed == new_feed and find([existing], name) is None:
        existing.aliases.append(name.strip())  # another name of the same employer: one entry, one feed
    if existing.status in ("followed", "dormant") and status != "followed":
        return existing, False
    if existing.status == "dormant":
        existing.last_relevant = now  # followed again: the retirement clock restarts
    existing.feed, existing.status, existing.reason = new_feed, status, reason
    existing.refusal = refusal if status == "unfollowable" else None
    existing.evidence = evidence or existing.evidence
    existing.first_seen = existing.first_seen or now
    return existing, False


_SHARED_EVIDENCE = "shared by several agencies; led to by: "


def shared_name(platform: str, entry: str) -> str | None:
    """The name of the feed ``platform:entry`` when it serves several employers (a registry kept by the
    platform's scraper module, read at call time like `ats_detect` does), else None."""
    if platform != "hr_manager":
        return None
    return importlib.import_module("door.scrapers.feeds.hr_manager").shared_name(entry)


def _record_shared(
    items: list[Company], name: str, feed: tuple[str, str], found_via: str, evidence: str | None, now: str,
) -> tuple[Company, bool]:
    """Record *name* as one more agency on a shared feed: one entry for the feed, named for it, with the
    agencies in ``evidence`` (and none in ``aliases``, which would make them one employer for dedup)."""
    label = shared_name(*feed)
    agency = name.strip()
    existing = find_by_feed(items, *feed)
    agencies: list[str] = []
    if existing is not None:
        if existing.evidence and existing.evidence.startswith(_SHARED_EVIDENCE):
            agencies += [a for a in existing.evidence[len(_SHARED_EVIDENCE):].split("; ") if a]
        if name_key(existing.name) != name_key(label):
            agencies.append(existing.name)
        agencies += existing.aliases
    agencies.append(agency)
    seen: set[str] = set()
    agencies = [a for a in agencies if name_key(a) != name_key(label) and not (name_key(a) in seen or seen.add(name_key(a)))]
    items[:] = [c for c in items if not (c.feed is None and c.status in ("unresolved", "unfollowable")
                                          and name_key(c.name) == name_key(agency) and c is not existing)]
    text = _SHARED_EVIDENCE + "; ".join(agencies) if agencies else evidence
    if existing is None:
        company = Company(name=label, feed=Feed(platform=feed[0], id=feed[1]), status="followed", found_via=found_via,
                          evidence=text, first_seen=now, last_checked=now)
        items.append(company)
        return company, True
    if existing.status == "dormant":
        existing.last_relevant = now
    existing.name, existing.aliases, existing.evidence = label, [], text
    existing.status, existing.reason, existing.last_checked = "followed", None, now
    existing.first_seen = existing.first_seen or now
    return existing, False


RETRY_DAYS = 90  # an employer found unfollowable or unresolved is not looked at again for this long


def is_settled(items: list[Company], name: str, now: datetime | None = None) -> bool:
    """Whether `follow` need not look at *name*: it is followed, or was found unfollowable or
    unresolved less than `RETRY_DAYS` ago."""
    company = find(items, name)
    if company is None:
        return False
    if company.status == "followed":
        return True
    if company.status == "dormant":
        return False  # seen again with a fitting ad, it is followed again
    checked = _parse(company.last_checked)
    return checked is not None and (now or datetime.now(timezone.utc)) - checked < timedelta(days=RETRY_DAYS)


def set_collect_problem(company: Company, outcome: str | None, reason: str, now: str) -> None:
    """Stamp why *company*'s feed could not be read (``blocked`` | ``failed``), or clear it with ``None``."""
    company.collect_problem = CollectProblem(at=now, outcome=outcome, reason=reason) if outcome else None


def mark_relevant(items: list[Company], name: str, now: str) -> Company | None:
    """Stamp ``last_relevant`` of the employer named *name* (or an alias) and return it; None
    when it is not on the list."""
    company = find(items, name)
    if company is not None:
        company.last_relevant = now
    return company


def shared_feed_of_job(items: list[Company], job_id: str) -> Company | None:
    """The followed shared feed a posting came from (its id is ``hr_manager.<alias>-<n>``), else None."""
    for company in items:
        if company.feed and shared_name(company.feed.platform, company.feed.id):
            if job_id.startswith(f"{company.feed.platform}.{company.feed.id.lower()}-"):
                return company
    return None


def mark_relevant_posting(items: list[Company], company: str, job_id: str, now: str) -> bool:
    """Stamp ``last_relevant`` of the employer a posting belongs to: the one named *company*, and the
    shared feed the posting came from (which names the hiring agency, not itself). True if any."""
    named = mark_relevant(items, company, now) is not None
    feed = shared_feed_of_job(items, job_id or "")
    if feed is not None:
        feed.last_relevant = now
    return named or feed is not None


def retire_idle(items: list[Company], days: int | None, now: datetime | None = None) -> list[Company]:
    """Make dormant (in place) every followed employer with no relevant job for *days* days and return them.

    The period runs from the later of ``first_seen`` and ``last_relevant``. ``days`` of 0 or None
    retires nobody, and an employer added by hand (``found_via`` "manual") is never retired."""
    if not days:
        return []
    now = now or datetime.now(timezone.utc)
    retired = []
    for company in items:
        if company.status != "followed" or company.found_via == "manual":
            continue
        since = [t for t in (_parse(company.first_seen), _parse(company.last_relevant)) if t is not None]
        if since and now - max(since) > timedelta(days=days):
            company.status, company.reason = "dormant", f"no relevant job in {days} days"
            retired.append(company)
    return retired


def reactivate(company: Company, now: str) -> None:
    """Follow a dormant employer again on the feed it kept; its clock restarts."""
    company.status, company.reason, company.last_relevant = "followed", None, now


def _parse(value: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def remove(items: list[Company], name: str) -> list[Company]:
    """Remove every entry named *name* from *items* (in place); returns what was removed."""
    removed = [c for c in items if find([c], name) is not None]
    items[:] = [c for c in items if find([c], name) is None]
    return removed


def feed_entries(profile_dir: Path | None, platform: str) -> list[str]:
    """The ids of the employers followed on *platform*, in file order."""
    return [c.feed.id for c in load(profile_dir) if c.status == "followed" and c.feed and c.feed.platform == platform]


def feed_config(profile_dir: Path | None) -> dict[str, list[str]]:
    """Each platform's followed ids under the config key its scraper reads (`sites.FEED_SITES`);
    platforms nobody follows are left out. The seam between the employer list and the stateless
    scrapers: `_scrape_core` merges this into the config it hands them."""
    out: dict[str, list[str]] = {}
    for company in load(profile_dir):
        if company.status == "followed" and company.feed:
            out.setdefault(sites.FEED_SITES[company.feed.platform], []).append(company.feed.id)
    return out


def entry_key(entry: str) -> str:
    """A feed entry as a lookup key: stripped, lower case, without scheme or trailing slash."""
    text = entry.strip().lower()
    for scheme in ("https://", "http://"):
        if text.startswith(scheme):
            text = text[len(scheme):]
    return text.rstrip("/")


def feed_names(items: list[Company]) -> dict[str, dict[str, str]]:
    """The followed employers' names under the config key their scraper reads, keyed by
    `entry_key` of the feed id: `{config_key: {entry: name}}`. `_scrape_core` hands it to the
    scrapers as `config["_names"]`, so a posting carries the employer's name, not the feed's guess."""
    out: dict[str, dict[str, str]] = {}
    for company in items:
        if company.status == "followed" and company.feed:
            out.setdefault(sites.FEED_SITES[company.feed.platform], {})[entry_key(company.feed.id)] = company.name
    return out


# --------------------------------------------------------------------------- #
# Display names
# --------------------------------------------------------------------------- #

_SECOND_LEVEL = {"co", "com", "org", "ac", "gov", "net"}


_POD = re.compile(r"(?:wd|em|fa|eu|us)\d*|\d+|[a-z]{2}(?:-[a-z]{2})?")  # Workday/Oracle pods, locales
_SLUG_NUMBER = re.compile(r"([^\W\d_]{3,})\d+")  # a tenant id's counter: "Ramboll3"


def guess_name(entry: str) -> str:
    """A display name from a feed entry: a slug, a board URL or a career host. A host on a career
    platform (`ats_detect.platform_domains`) gives its tenant, never the platform (#436)."""
    text = entry.strip()
    if "://" in text or "." in text:
        url = text if "://" in text else f"https://{text}"
        det = ats_detect.from_url(url)
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(":")[0]
        generic = set(i18n.generic_host_labels())
        platform = ats_detect.platform_domain_of(host)
        if det is not None and det.entry and "." not in det.entry:
            text = det.entry
        elif platform is not None:
            text = _tenant(host[: -len(platform)], parsed.path, generic) or host
        else:
            labels = host.split(".")
            if len(labels) > 1:
                labels = labels[:-2] if len(labels) > 2 and labels[-2] in _SECOND_LEVEL else labels[:-1]
            labels = [l for l in labels if l not in generic] or labels
            text = labels[-1] if labels else host
    number = _SLUG_NUMBER.fullmatch(text)
    text = number.group(1) if number else text
    words = [w for w in re.split(r"[-_\s]+", text) if w]
    return " ".join(w.capitalize() for w in words) or entry.strip()


def _tenant(prefix: str, path: str, generic: set[str]) -> str:
    """The customer's label in a platform host's *prefix* (``dca.career.``, ``novonordisk.wd3.``), else
    in its path (``wd3.myworkdaysite.com/recruiting/acme``); "" when neither names one."""
    labels = [l for l in prefix.strip(".").split(".") if l and l not in generic]
    named = [l for l in labels if not _POD.fullmatch(l)]
    segments = [p for p in path.lower().split("/") if p and p not in generic and not _POD.fullmatch(p)]
    return next(iter(named or segments or labels), "")


def _platform_name(name: str) -> bool:
    """Whether *name* is a career platform's own ("Emply", "Workday", "SmartRecruiters")."""
    key = name_key(name)
    labels = {d.split(".")[0].replace("-", "") for d in ats_detect.platform_domains()}
    return any(key == label or (len(key) >= 5 and key in label) for label in labels)


_TITLE_SEP = re.compile(r"\s+[|\u2013\u2014:·]\s+|\s+[|\u2013\u2014:·]$|\s+-\s+|\s+I\s+")  # " I ": Emply's pipe


def _page_candidates(soup: BeautifulSoup) -> list[str]:
    out = []
    og = soup.find("meta", attrs={"property": "og:site_name"})
    if og is not None and og.get("content"):
        out.append(og["content"])
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                org = node.get("hiringOrganization")
                if isinstance(org, dict) and isinstance(org.get("name"), str):
                    out.append(org["name"])
                elif isinstance(org, str):
                    out.append(org)
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    if soup.title is not None:
        words = i18n.word_pattern(i18n.career_site_words())
        parts = _TITLE_SEP.split(" ".join(soup.title.get_text().split()))
        parts = [re.sub(rf"^{words}\s+(?:at|hos|vid|i|in|with|@)\s+", "", p.strip(), flags=re.IGNORECASE) for p in parts]
        parts = [p for p in parts if p and not re.fullmatch(rf"(?:{words}\s*)+", p, re.IGNORECASE)]
        if parts:
            out.append(parts[-1])
    return out


def name_from_page(html: str) -> str:
    """The employer a careers page names: its ``og:site_name``, else a JSON-LD ``hiringOrganization``,
    else its ``<title>`` without the careers words around it; "" when it names only a career platform
    (`_platform_name`) or nothing. Pure (#436)."""
    soup = BeautifulSoup(html or "", "html.parser")
    generic = set(i18n.generic_host_labels())
    for name in _page_candidates(soup):
        name = " ".join(name.split())
        if name and name.lower() not in generic and not _platform_name(name):
            return name
    return ""


# --------------------------------------------------------------------------- #
# Duplicates: merging, proposing, and the employer of a posting (#314)
# --------------------------------------------------------------------------- #

_RANK = {"followed": 3, "dormant": 2}


def _later(a: str | None, b: str | None) -> str | None:
    pa, pb = _parse(a), _parse(b)
    if pa is None or pb is None:
        return a if pb is None else b
    return a if pa >= pb else b


def _earlier(a: str | None, b: str | None) -> str | None:
    pa, pb = _parse(a), _parse(b)
    if pa is None or pb is None:
        return a if pb is None else b
    return a if pa <= pb else b


def _same_feed(a: Feed | None, b: Feed | None) -> bool:
    return a is not None and b is not None and a.platform == b.platform and a.id.lower() == b.id.lower()


def merge(items: list[Company], a: str, b: str) -> Company:
    """Fold the employer named *b* into the one named *a* (in place) and return the survivor.

    A keeps its name; B's name and aliases become A's aliases (never one equal to A's own name); the
    evidence of both is kept; ``first_seen`` is the earliest, ``last_checked`` and ``last_relevant`` the
    latest. The one that is followed (else dormant) gives the status, feed and reason; two followed
    employers on different feeds are not merged.

    Raises:
        CompaniesError: a name is not on the list, both are the same entry, or both are followed on different feeds.
    """
    first, second = find_exact(items, a), find_exact(items, b)
    if first is None or second is None:
        raise CompaniesError(f"{a if first is None else b!r} is not on the list")
    if first is second:
        raise CompaniesError(f"{a!r} and {b!r} are the same employer")
    if first.status == second.status == "followed" and not _same_feed(first.feed, second.feed):
        raise CompaniesError(f"{first.name!r} and {second.name!r} are followed on different feeds; remove one first")
    if _RANK.get(second.status, 1) > _RANK.get(first.status, 1):
        first.status, first.feed, first.reason = second.status, second.feed, second.reason
    first.aliases = [n for n in _dedupe([*first.aliases, second.name, *second.aliases])
                     if name_key(n) != name_key(first.name)]
    parts = [t for t in (first.evidence, second.evidence) if t]
    first.evidence = "; ".join(dict.fromkeys(parts)) or None
    first.first_seen = _earlier(first.first_seen, second.first_seen)
    first.last_checked = _later(first.last_checked, second.last_checked)
    first.last_relevant = _later(first.last_relevant, second.last_relevant)
    items[:] = [c for c in items if c is not second]
    return first


def merge_candidates(items: list[Company]) -> list[dict]:
    """The groups of entries that look like one employer, for the user to confirm one by one:
    ``[{"names": [...], "reason": "same feed" | "same name"}]``. Entries on a shared feed
    (`shared_name`: one feed, many employers) are left out of the feed comparison."""
    parent = list(range(len(items)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    reasons: dict[int, str] = {}
    owner: dict[tuple, int] = {}
    for i, company in enumerate(items):
        keys = []
        if company.feed and not shared_name(company.feed.platform, company.feed.id):
            keys.append(("same feed", company.feed.platform, company.feed.id.lower()))
        keys += [("same name", name_key(n)) for n in _names(company)]
        for key in dict.fromkeys(keys):
            j = owner.setdefault(key, i)
            if root(j) != root(i):
                parent[root(i)] = root(j)
                reasons.setdefault(root(j), key[0])
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(root(i), []).append(i)
    out = []
    for members in groups.values():
        if len(members) > 1:
            reason = next((reasons[r] for r in {root(m) for m in members} if r in reasons), "same name")
            out.append({"names": [items[m].name for m in members], "reason": reason})
    return out


def employer_of(items: list[Company], company: str, job_id: str) -> str | None:
    """The name of the entry a posting belongs to: the one that *company* names (or aliases), else the
    shared feed the job came from, else None."""
    entry = find(items, company) if company.strip() else None
    entry = entry or shared_feed_of_job(items, job_id or "")
    return entry.name if entry else None
