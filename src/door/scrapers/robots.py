"""robots.txt rules as RFC 9309 defines them, for The other door's product token (issue #226).

`parse(text)` picks the group for ``door`` (or, without one, the ``*`` group)
and returns `Rules`: `allowed(path)` lets the longest matching rule win, an
``Allow`` winning a tie, with ``*`` matching any run of characters and a trailing
``$`` anchoring the end. Python's `urllib.robotparser` is not used: it ignores
both wildcards and lets the first matching rule win, which reads files such as
Jobindex's and HR-Manager's the opposite way from every major crawler.

`Crawl-delay` is not in the RFC but widely used (Lever asks for 1 s); it is read
from the same group. Pure: fetching robots.txt is `PoliteSession`'s job.
"""

import re
import urllib.parse
from dataclasses import dataclass, field

# The product token door matches `User-agent` lines against, so a group a site
# writes for door applies to it (its User-Agent header is a browser's: see
# `http_client.USER_AGENT`).
PRODUCT_TOKEN = "door"


@dataclass(frozen=True)
class Rules:
    """The allow/disallow rules of one robots.txt group (merged when several match)."""

    rules: tuple[tuple[bool, str], ...] = ()  # (allow, normalised pattern)
    crawl_delay: float | None = None
    sitemaps: tuple[str, ...] = ()  # the file's `Sitemap:` lines, which belong to no group
    blocked: bool = False  # robots.txt unreachable: assume complete disallow (RFC 9309 §2.3.1.4)
    _compiled: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def allow_all(cls) -> "Rules":
        return cls()

    @classmethod
    def disallow_all(cls) -> "Rules":
        return cls(blocked=True)

    def allowed(self, path: str) -> bool:
        """Whether `path` (path plus query, as `path_of` gives it) may be fetched."""
        if self.blocked:
            return False
        target = _normalise(path or "/")
        best_len, best_allow = -1, True
        for allow, pattern in self.rules:
            if not pattern:
                continue  # an empty Disallow allows everything; an empty Allow says nothing
            if self._regex(pattern).match(target) is None:
                continue
            if len(pattern) > best_len or (len(pattern) == best_len and allow):
                best_len, best_allow = len(pattern), allow
        return best_allow

    def _regex(self, pattern: str) -> re.Pattern:
        regex = self._compiled.get(pattern)
        if regex is None:
            anchored = pattern.endswith("$")
            body = pattern[:-1] if anchored else pattern
            regex = re.compile(".*".join(re.escape(part) for part in body.split("*")) + ("$" if anchored else ""))
            self._compiled[pattern] = regex
        return regex


def path_of(url: str) -> str:
    """The part of `url` robots rules are matched against: its path and query."""
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def parse(text: str) -> Rules:
    """The rules that apply to door in the robots.txt `text`."""
    groups: list[tuple[list[str], list[tuple[bool, str]], list[float]]] = []
    sitemaps: list[str] = []
    agents: list[str] | None = None  # the user-agent lines of the group being read
    for raw in text.lstrip("﻿").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "sitemap":
            if value:
                sitemaps.append(value)
        elif key == "user-agent":
            if agents is None or groups[-1][1] or groups[-1][2]:
                agents = []
                groups.append((agents, [], []))
            agents.append(value.lower())
        elif agents is None:
            continue  # a rule before any user-agent line belongs to no group
        elif key in ("allow", "disallow"):
            groups[-1][1].append((key == "allow", _normalise(value)))
        elif key == "crawl-delay":
            try:
                groups[-1][2].append(float(value))
            except ValueError:
                pass

    chosen = [g for g in groups if PRODUCT_TOKEN in g[0]] or [g for g in groups if "*" in g[0]]
    rules = tuple(rule for g in chosen for rule in g[1])
    delays = [d for g in chosen for d in g[2]]
    return Rules(rules=rules, crawl_delay=max(delays) if delays else None, sitemaps=tuple(sitemaps))


def _normalise(s: str) -> str:
    """Percent-escapes upper-cased and non-ASCII characters escaped, so equal URLs compare equal."""
    s = urllib.parse.quote(s, safe="".join(chr(c) for c in range(33, 127)))
    return re.sub(r"%[0-9a-fA-F]{2}", lambda m: m.group(0).upper(), s)
