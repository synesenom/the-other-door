"""Which postings are local to the profile, before anything is fetched. Pure.

Global employers (Cisco, Microsoft on Workday) list thousands of jobs nowhere near the user. Two
cheap tests drop them: the place names in a job's URL path (`path_is_non_local`) and the location
facets of a Workday job list (`location_filter`). Both only act when the profile's `location` names a
country the i18n data knows, and both keep what says nothing about a place and what is remote.
`location_is_non_local` judges the free-text location a feed already parsed (place names, or a bare
ISO country code such as ``, DE``) before the posting is saved.
Place names come from `src/door/i18n` (the country files, `common.toml`'s ``foreign_places``).
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from door import i18n
from door.matching import title_fit

_LOCATION_ORDER = ("locationcountry", "locationhierarchy1", "locations")  # country level first, then the sites


def enabled(config: dict) -> bool:
    """Whether the profile's location names a country with an i18n file."""
    return i18n.country_for_location(str(config.get("location") or "")) is not None


def country_code(config: dict) -> str | None:
    """The lower-case ISO 3166 code of the profile's country, or None when it is unknown."""
    country = i18n.country_for_location(str(config.get("location") or ""))
    return country.code.lower() if country is not None else None


def country_is_non_local(country: str | None, config: dict, *, remote: bool = False) -> bool:
    """Whether a posting stating its *country* (an ISO code) is in another country than the profile's.
    Remote work, a posting with no country, and a profile with no known country are never non-local."""
    code = country_code(config)
    return bool(code and country and not remote and str(country).strip().lower() != code)


def local_names(config: dict) -> list[str]:
    """The profile's location parts, its country's names and every name of that country's cities."""
    location = str(config.get("location") or "")
    names = [part.strip() for part in location.split(",") if part.strip()]
    country = i18n.country_for_location(location)
    if country is not None:
        names += [country.name, *country.names]
        for city, aliases in country.cities.items():
            names += [city, *aliases]
    return names


def _foreign_pattern(config: dict) -> re.Pattern | None:
    local = {title_fit.squash(n.rstrip("*")) for n in local_names(config)}
    return title_fit.name_pattern([n for n in i18n.foreign_places() if title_fit.squash(n) not in local])


def _remote() -> re.Pattern | None:
    return title_fit.name_pattern(i18n.marker_words("remote"))


def is_remote(text: str) -> bool:
    """Whether *text* holds a remote, hybrid or home-based word in any supported language."""
    remote = _remote()
    return bool(remote and remote.search(title_fit.squash(text or "")))


def _is_pinned_remote_and_foreign(text: str, config: dict) -> bool:
    """Whether *text* (from `squash`) is remote with a word that ties it to a place ("Remote, Portugal"),
    names another country's place and none of the profile's: the named country decides."""
    pinned = title_fit.name_pattern(i18n.marker_words("remote_pinned"))
    local, foreign = title_fit.name_pattern(local_names(config)), _foreign_pattern(config)
    return bool(pinned and foreign and pinned.search(text) and foreign.search(text) and not (local and local.search(text)))


def _is_non_local_text(text: str, config: dict) -> bool:
    """Whether *text* (place names, from `squash`) names another place and no local one, nor remote."""
    local, foreign, remote = title_fit.name_pattern(local_names(config)), _foreign_pattern(config), _remote()
    return bool(foreign and foreign.search(text) and not (local and local.search(text)) and not (remote and remote.search(text)))


def path_is_non_local(path: str, config: dict) -> bool:
    """Whether a job URL's *path* names another country's or city's place and none of the profile's own
    (``/job/Chicago-Illinois/...`` yes, ``/job/Ballerup-Denmark/...``, ``/job/Remote-Germany/...`` and a path
    naming no place no). Always False without a known country."""
    if not enabled(config):
        return False
    return _is_non_local_text(title_fit.squash(unquote(path)), config)


_CODE_PART = re.compile(r"^[A-Z]{2}$")
_CODE_ALIASES = {"uk": "gb"}  # a location writes the United Kingdom as UK, ISO 3166 calls it GB
_PART_SPLIT = re.compile(r"[,;/|]")


def location_is_non_local(text: str | None, config: dict) -> bool:
    """Whether a posting's free-text *location* is in another country than the profile's: it names a
    foreign place and no local one, or has a bare uppercase two-letter part (``London, UK``, ``Boston, MA``)
    that is not the profile's country code and no local name. Remote, empty and unknown-country are False,
    except a remote job that names another country and no local one ("Remote, Portugal")."""
    if not enabled(config) or not text or not str(text).strip():
        return False
    text = str(text)
    squashed = title_fit.squash(text)
    if _is_non_local_text(squashed, config) or _is_pinned_remote_and_foreign(squashed, config):
        return True
    code = country_code(config)
    codes = [p.strip() for p in _PART_SPLIT.split(text) if _CODE_PART.match(p.strip())]
    if not codes or any(_CODE_ALIASES.get(c.lower(), c.lower()) == code for c in codes):
        return False
    local, remote = title_fit.name_pattern(local_names(config)), _remote()
    return not (local and local.search(squashed)) and not (remote and remote.search(squashed))


def split_postings(postings: list[dict], config: dict) -> tuple[list[dict], int]:
    """*postings* without those whose `location` is non-local, and how many were dropped."""
    if not enabled(config):
        return list(postings), 0
    kept = [p for p in postings if not location_is_non_local(p.get("location"), config)]
    return kept, len(postings) - len(kept)


def split_urls(urls: list[str], config: dict) -> tuple[list[str], int]:
    """*urls* without the non-local ones, and how many were dropped."""
    if not enabled(config):
        return list(urls), 0
    kept = [u for u in urls if not path_is_non_local(urlparse(u).path, config)]
    return kept, len(urls) - len(kept)


def _location_params(facets) -> dict[str, list[dict]]:
    """``{facetParameter: [leaf value, ...]}`` of every location facet of a Workday answer: top level
    (``locationCountry``) or nested in a ``locationMainGroup`` (``locations``, ``locationHierarchy1``)."""
    found: dict[str, list[dict]] = {}

    def visit(facet) -> None:
        if not isinstance(facet, dict):
            return
        values = [v for v in facet.get("values") or [] if isinstance(v, dict)]
        nested = [v for v in values if "values" in v]
        for child in nested:
            visit(child)
        param = str(facet.get("facetParameter") or "")
        if param.lower().startswith("location") and param.lower() != "locationmaingroup" and not nested:
            found.setdefault(param, []).extend(v for v in values if v.get("id"))

    for facet in facets if isinstance(facets, list) else []:
        visit(facet)
    return found


def location_filter(facets, config: dict) -> tuple[str, list[str]] | None:
    """``(facet parameter, value ids)`` to apply to a Workday job list so it holds only local jobs: the
    values of the most general location facet (country, then site) that name the profile's country or
    city, plus a bare "Remote". ``(param, [])`` when the tenant has no local location at all; None when
    nothing can be said (no country known, no location facet). Pure."""
    if not enabled(config):
        return None
    params = _location_params(facets)
    if not params:
        return None
    order = sorted(params, key=lambda p: (_LOCATION_ORDER.index(p.lower()) if p.lower() in _LOCATION_ORDER else len(_LOCATION_ORDER), p))
    local, remote = title_fit.name_pattern(local_names(config)), _remote()
    for param in order:
        values = params[param]
        ids = [v["id"] for v in values if local and local.search(title_fit.squash(str(v.get("descriptor") or "")))]
        if ids:
            bare = [v["id"] for v in values if remote and title_fit.squash(str(v.get("descriptor") or "")) == "remote"]
            return param, ids + [i for i in bare if i not in ids]
    return order[0], []
