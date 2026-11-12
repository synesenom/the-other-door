"""An employer's own website from its name, read from Wikidata (issue #566).

A board or a register names a large employer by its legal name ("Telia Sverige AB", "Hilti Svenska Aktiebolag")
with no link to its own site, so `follow` cannot find its feed. Wikidata (public, CC0, no key, no login) knows
most large employers with their official website (property P856), their country (P17) and their parent
organisation (P749). `Lookup.employer` asks its API for the name, trimmed of its legal form and of the words a
subsidiary's name ends with (`i18n.subsidiary_words`: "GBC", "Svenska", "i Sverige"), keeps the hits whose
label or matched alias is that name (`companies.name_key`), and picks the organisation among them, one in the
profile's country first. `follow` (`commands/companies._by_website`) then reads that website, its parent's and
their careers pages through the same detection as any link.

Polite and bounded: two searches, one or two entity reads per employer (the country's item once per run), on the
caller's `PoliteSession`; at most `MAX_LOOKUPS` names a run, each name looked up once; a refusal or a server
error is waited out once (``Retry-After``, capped, else a fixed rest; every lookup waits with the one that
met it) and the request asked again, only a second refusal stops the lookups for the run. Failures are notes,
never raised. A name left unasked (stopped, budget spent) says so (`is_unasked`): `follow` keeps that employer
queued for a later run instead of recording it as unresolved.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests

from door import i18n
from door.core import ats_detect
from door.core import companies as store

API = "https://www.wikidata.org/w/api.php"
MAX_LOOKUPS = 60        # names looked up on Wikidata per run
_MAX_HITS = 20          # search hits read per query
_MAX_ENTITIES = 8       # matching hits whose entity is read
_REST_S = 60.0          # a 429 or server error is waited out this long (a Retry-After wins, up to this), once

_WEBSITE, _COUNTRY, _PARENT, _INSTANCE = "P856", "P17", "P749", "P31"
# Statements only an organisation has: headquarters, industry, legal form, employees, parent, subsidiary.
_ORG_PROPS = {"P159", "P452", "P1454", "P1128", "P749", "P355"}
# Classes that make an item an organisation: organisation, business, company, enterprise, public company.
_ORG_CLASSES = {"Q43229", "Q4830453", "Q783794", "Q6881511", "Q891723"}
_PUNCT = ".,;:()[]\"'"


# --------------------------------------------------------------------------- #
# The name Wikidata knows (pure)
# --------------------------------------------------------------------------- #

def _fold(word: str) -> str:
    return word.strip(_PUNCT).lower()


def _phrases(words: list[str]) -> list[list[str]]:
    """Each phrase as its folded words, longest first."""
    out = {tuple(_fold(w) for w in phrase.split() if _fold(w)) for phrase in words}
    return sorted((list(p) for p in out if p), key=len, reverse=True)


def _strip_tail(name: str, phrases: list[list[str]]) -> str:
    """*name* without the *phrases* it ends with, repeatedly; never down to nothing."""
    words = name.split()
    changed = True
    while changed:
        changed = False
        folded = [_fold(w) for w in words]
        while len(words) > 1 and not any(ch.isalnum() for ch in folded[-1]):   # a lone "&" or "-" left at the end
            words, folded = words[:-1], folded[:-1]
        for phrase in phrases:
            if len(phrase) < len(words) and folded[-len(phrase):] == phrase:
                words, changed = words[:-len(phrase)], True
                break
    return " ".join(words).strip()


def _legal() -> list[list[str]]:
    return _phrases(i18n.slug_suffixes())


def _all_tails() -> list[list[str]]:
    return _phrases([*i18n.slug_suffixes(), *i18n.subsidiary_words()])


def trimmed(name: str) -> str:
    """The employer's own name in a register's name: its legal form and the words a subsidiary's name ends with
    (the country's names among them) dropped from its end ("Telia Sverige AB" -> "Telia"). Pure."""
    return _strip_tail(" ".join(name.split()), _all_tails())


def queries(name: str) -> list[str]:
    """What Wikidata is searched for: the name without its legal form (a subsidiary Wikidata knows by that name,
    "Telia Sverige"), then without its subsidiary words too ("Telia"). Pure."""
    name = " ".join(name.split())
    return [q for q in dict.fromkeys([_strip_tail(name, _legal()), trimmed(name)]) if q]


def core_key(text: str) -> str:
    """The lookup form (`companies.name_key`) of a name's trimmed form: equal for a subsidiary and its group."""
    return store.name_key(trimmed(text or ""))


def matching_ids(hits: list[dict], name: str) -> list[str]:
    """The ids of the search *hits* whose label or matched alias is *name* (by `core_key`), in order. Pure."""
    key = core_key(name)
    out = []
    for hit in hits:
        texts = [hit.get("label") or "", ((hit.get("match") or {}).get("text")) or ""]
        if hit.get("id") and any(t and core_key(t) == key for t in texts):
            out.append(hit["id"])
    return list(dict.fromkeys(out))


def _statements(entity: dict, prop: str) -> list:
    """The values of *entity*'s *prop* statements, preferred first, deprecated left out (an item's id for an item)."""
    ranked = [s for s in (entity.get("claims") or {}).get(prop) or [] if s.get("rank") != "deprecated"]
    ranked.sort(key=lambda s: s.get("rank") != "preferred")
    out = []
    for statement in ranked:
        value = ((statement.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        value = value.get("id") if isinstance(value, dict) else value
        if value:
            out.append(value)
    return out


def is_organisation(entity: dict) -> bool:
    """Whether the item is an organisation: one of the statements only an organisation has, or an organisation's
    class. Not a person, a place, a document or a family name of the same name. Pure."""
    claims = set((entity.get("claims") or {}))
    return bool(claims & _ORG_PROPS) or bool(set(_statements(entity, _INSTANCE)) & _ORG_CLASSES)


def website_of(entity: dict, tlds: tuple[str, ...] = ()) -> str | None:
    """The item's official website: the one on the profile country's domain (*tlds*), else a ``.com`` one, else
    the first. Pure."""
    sites = [s for s in _statements(entity, _WEBSITE) if isinstance(s, str) and s.startswith("http")]
    hosts = [ats_detect.safe_urlparse(s).netloc.lower() for s in sites]
    for wanted in (*tlds, "com"):
        for site, host in zip(sites, hosts):
            if host.endswith("." + wanted):
                return site
    return sites[0] if sites else None


def choose(entities: dict, ids: list[str], country: str | None, tlds: tuple[str, ...] = ()) -> str | None:
    """The id of the employer among the matching *ids*: an organisation with a website (or a parent that may have
    one), one in *country* (its item's id) first, then one with a website of its own, then the search's order. Pure."""
    ranked = []
    for index, qid in enumerate(ids):
        entity = entities.get(qid)
        if not entity or not is_organisation(entity):
            continue
        website, parent = website_of(entity, tlds), _statements(entity, _PARENT)
        if website is None and not parent:
            continue
        local = country is not None and country in _statements(entity, _COUNTRY)
        ranked.append((not local, website is None, index, qid))
    return min(ranked)[3] if ranked else None


def _label(entity: dict, language: str) -> str:
    labels = entity.get("labels") or {}
    for code in ("en", language, "mul"):
        value = (labels.get(code) or {}).get("value")
        if value:
            return value
    return str(entity.get("id") or "")


@dataclass(frozen=True)
class Employer:
    """An organisation Wikidata knows: its item, label, official website, whether it is in the profile's
    country, and its parent organisation (another `Employer`, or None)."""

    qid: str
    label: str
    website: str | None
    local: bool
    parent: Employer | None = None

    def sites(self) -> list[str]:
        """Its website, then its parent's (a subsidiary often posts on its group's careers site)."""
        found = [self.website, self.parent.website if self.parent else None]
        return list(dict.fromkeys(s for s in found if s))

    def names(self) -> list[str]:
        """Its label, then its parent's."""
        return list(dict.fromkeys(n for n in (self.label, self.parent.label if self.parent else None) if n))


# --------------------------------------------------------------------------- #
# The lookup
# --------------------------------------------------------------------------- #

def _rest(seconds: float) -> None:
    time.sleep(seconds)


_UNASKED = ("Wikidata not asked:", "Wikidata stopped answering")


def is_unasked(note: str | None) -> bool:
    """Whether *note* (a `Lookup.employer` reason) says the name went unasked: the lookups stopped or the run's
    budget was spent. Such an employer is worth asking again on a later run. Pure."""
    return bool(note) and note.startswith(_UNASKED)


def _retry_after(exc: requests.HTTPError) -> float:
    header = (exc.response.headers.get("Retry-After", "") if exc.response is not None else "").strip()
    try:
        return min(max(float(header), 0.0), _REST_S) if header else _REST_S
    except ValueError:
        return _REST_S


class _Refused(Exception):
    """Wikidata answered 429 or a server error: no more lookups this run (after one wait and a second try)."""


class Lookup:
    """Looks employers up on Wikidata for one run: shared by the employers `follow` checks in parallel. Each
    name (by `core_key`) is looked up once; at most *max_lookups* names; a refusal is waited out once, the second stops it."""

    def __init__(self, location: str = "", max_lookups: int = MAX_LOOKUPS) -> None:
        country = i18n.country_for_location(location or "")
        self.code = country.code if country is not None else None
        self.language = country.languages[0] if country is not None and country.languages else "en"
        self.tlds = tuple(country.tlds or [country.code]) if country is not None else ()
        self.max_lookups = max_lookups
        self._used = 0
        self._stopped: str | None = None
        self._country: str | None | bool = False   # False: not asked yet
        self._cache: dict[str, tuple[Employer | None, str | None]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._resting_until = 0.0   # monotonic time before which nobody asks (a 429 is being waited out)

    def employer(self, session, name: str) -> tuple[Employer | None, str | None]:
        """``(employer, None)`` for the organisation Wikidata knows by *name*, else ``(None, why)``. Never raises."""
        key = core_key(name)
        with self._lock:
            key_lock = self._locks.setdefault(key, threading.Lock())
        with key_lock:   # the same employer under two names (two threads) is looked up once
            with self._lock:
                if key in self._cache:
                    return self._cache[key]
                if self._stopped:
                    return None, self._stopped
                if self._used >= self.max_lookups:
                    return None, f"Wikidata not asked: this run's budget of {self.max_lookups} lookups is spent"
                self._used += 1
            try:
                result = self._look_up(session, name)
            except _Refused as exc:
                with self._lock:
                    self._stopped = f"Wikidata stopped answering this run ({exc})"
                    return None, self._stopped
            except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                return None, f"Wikidata did not answer for {trimmed(name)!r} ({type(exc).__name__})"
            with self._lock:
                self._cache[key] = result
            return result

    def _pause(self) -> None:
        """Wait while another lookup rests after a refusal: nobody asks Wikidata meanwhile."""
        with self._lock:
            remaining = self._resting_until - time.monotonic()
        if remaining > 0:
            _rest(remaining)

    def _fetch(self, session, params: dict, pause: bool = True):
        if pause:
            self._pause()
        return session.get(API, params={**params, "format": "json"}, headers={"Accept": "application/json"})

    def _get(self, session, params: dict) -> dict:
        try:
            try:
                resp = self._fetch(session, params)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status != 429 and status < 500:
                    raise
                wait = _retry_after(exc)
                with self._lock:
                    self._resting_until = max(self._resting_until, time.monotonic() + wait)
                _rest(wait)
                resp = self._fetch(session, params, pause=False)  # it has just rested
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status == 429 or status >= 500:
                raise _Refused(f"it answered {status}") from exc
            raise
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        if "error" in data:
            raise ValueError(str((data["error"] or {}).get("code")))
        return data

    def _search(self, session, text: str) -> list[dict]:
        data = self._get(session, {"action": "wbsearchentities", "search": text, "language": self.language,
                                   "uselang": "en", "type": "item", "limit": _MAX_HITS})
        return [h for h in data.get("search") or [] if isinstance(h, dict)]

    def _entities(self, session, ids: list[str]) -> dict:
        data = self._get(session, {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels",
                                   "languages": "|".join(dict.fromkeys(["en", self.language]))})
        return {q: e for q, e in (data.get("entities") or {}).items() if isinstance(e, dict) and "missing" not in e}

    def _country_item(self, session) -> str | None:
        """The item of the profile's country (its ISO code, P297), asked once a run."""
        with self._lock:
            if self._country is not False:
                return self._country  # type: ignore[return-value]
        data = self._get(session, {"action": "query", "list": "search", "srsearch": f"haswbstatement:P297={self.code.upper()}",
                                   "srlimit": 1, "srprop": ""})
        hits = (data.get("query") or {}).get("search") or []
        item = hits[0].get("title") if hits else None
        with self._lock:
            self._country = item
        return item

    def _look_up(self, session, name: str) -> tuple[Employer | None, str | None]:
        hits: list[dict] = []
        for text in queries(name):
            hits += self._search(session, text)
        ids = matching_ids(hits, name)[:_MAX_ENTITIES]
        unknown = f"Wikidata knows no organisation named {trimmed(name)!r} with a website"
        if not ids:
            return None, unknown
        entities = self._entities(session, ids)
        country = self._country_item(session) if self.code else None
        qid = choose(entities, ids, country, self.tlds)
        if qid is None:
            return None, unknown
        entity = entities[qid]
        parent = None
        parent_ids = [p for p in _statements(entity, _PARENT) if isinstance(p, str)][:1]
        if parent_ids:
            parent_entity = self._entities(session, parent_ids).get(parent_ids[0])
            if parent_entity is not None and is_organisation(parent_entity):
                parent = self._employer(parent_entity, country)
        return self._employer(entity, country, parent), None

    def _employer(self, entity: dict, country: str | None, parent: Employer | None = None) -> Employer:
        local = country is not None and country in _statements(entity, _COUNTRY)
        return Employer(str(entity.get("id")), _label(entity, self.language), website_of(entity, self.tlds), local, parent)
