"""Shared polite HTTP client for job-board scrapers.

Provides ``PoliteSession``, a thin wrapper around ``requests.Session`` that adds:
- A common desktop Firefox's ``User-Agent`` (`USER_AGENT`).
- ``robots.txt`` read once per origin per session: RFC 9309 rules for The other door's
  product token (`door.scrapers.robots`), for its ``Sitemap:`` lines and
  ``Crawl-delay``. When `OBEY_ROBOTS` is on (issue #226), every redirect hop is
  also checked against its own host's file, and a disallowed URL raises
  `RobotsBlocked` before it is requested; it is off.
- A jittered inter-request delay (``random.uniform(min_delay, max_delay)``), or
  the host's ``Crawl-delay`` when that is longer. Pacing is per host (issue
  #254): requests to one host go one at a time, each after its own pause, from
  however many threads; requests to different hosts never wait on each other.
- Exponential-jitter backoff on 429 / 5xx responses (``Retry-After`` header
  honoured when present), up to ``max_retries`` attempts before re-raising.
- Centralized timeout default.

Usage::

    session = PoliteSession(min_delay=0.8, max_delay=1.5, timeout=20)
    resp = session.get(url)
"""

import contextlib
import ipaddress
import random
import socket
import ssl
import threading
import time
import urllib.parse
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import requests
import truststore
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util import connection as _urllib3_connection

from door.scrapers import robots

# The User-Agent every request sends: a common desktop Firefox's. Not Chrome's: a real Chrome also
# sends client hints (`Sec-CH-UA`) and its own TLS handshake, so a plain request naming Chrome reads
# as a faked browser, which profession.hu's firewall blocks; Firefox sends no client hints.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) Gecko/20100101 Firefox/145.0"
_MAX_REDIRECTS = 10

# Whether robots.txt gates requests. Off: the bar is each site's terms. robots.txt is
# read for its Sitemap: lines and its Crawl-delay, which is always honoured; read when a session is made, so tests can patch it.
OBEY_ROBOTS = False

# The pause between requests to one employer-feed host (ashby, greenhouse, lever, recruitee,
# pinpoint, teamtailor, successfactors, hr_manager, workable, career_sites), in seconds.
FEED_DELAY = (0.2, 0.5)

# Default backoff constants
_BACKOFF_BASE = 2.0   # seconds
_BACKOFF_CAP = 30.0   # seconds maximum backoff


# The longest any single wait is: a host's Crawl-delay, a Retry-After, one backoff (#545). A host that asks
# for more is paced at this, so one site can never hold a run.
MAX_PAUSE_S = 60.0


class BudgetExceeded(RequestException):
    """Raised instead of waiting past the time budget of `budget()`."""


class Budget:
    """A time budget; ``hit`` says a request was refused for lack of time."""

    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds
        self.hit = False


_local = threading.local()


@contextlib.contextmanager
def budget(seconds: float):
    """For *seconds*, requests made by this thread wait no longer than what is left (they raise
    `BudgetExceeded` instead): one employer's checks cannot hold a run. Yields the `Budget`."""
    previous = getattr(_local, "budget", None)
    current = _local.budget = Budget(seconds)
    try:
        yield current
    finally:
        _local.budget = previous


def _wait(seconds: float) -> None:
    """Sleep *seconds* (at most `MAX_PAUSE_S`), or raise `BudgetExceeded` when this thread's budget has less left."""
    seconds = min(seconds, MAX_PAUSE_S)
    current = getattr(_local, "budget", None)
    if current is not None and current.deadline - time.monotonic() < seconds:
        current.hit = True
        raise BudgetExceeded("over its time budget")
    time.sleep(seconds)


class NotPublicAddress(RequestException):
    """The host is, or resolves to, an address on this computer or a private network (#548): never connected to."""


class BodyTooLarge(RequestException):
    """A response body passed `MAX_BODY_BYTES` once decoded."""


# The sitemap protocol's uncompressed maximum: no page, feed or sitemap this fetcher reads is larger.
MAX_BODY_BYTES = 50 * 1024 * 1024


# The 96-bit prefixes whose last 32 bits are an IPv4 address: NAT64, IPv4-translated (SIIT), IPv4-compatible.
_IPV4_CARRYING_PREFIXES = (
    bytes.fromhex("0064ff9b" + "00" * 8), bytes.fromhex("00" * 8 + "ffff0000"), bytes(12),
)


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether *ip* is on the public internet. An IPv6 address that carries an IPv4 one (IPv4-mapped,
    6to4, Teredo, NAT64 `64:ff9b::/96`, IPv4-translated `::ffff:0:a.b.c.d`, `::a.b.c.d`) is judged by the IPv4 address inside: `is_global`
    alone calls `64:ff9b::a00:1`, `::127.0.0.1` and `2002:7f00:1::` public. NAT64 is unwrapped, not
    refused: on a DNS64 network every IPv4-only site arrives there."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_public(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return _is_public(ip.sixtofour)
        if ip.teredo is not None:
            return all(_is_public(part) for part in ip.teredo)
        packed = ip.packed
        if packed[:12] in _IPV4_CARRYING_PREFIXES:
            return _is_public(ipaddress.IPv4Address(packed[12:]))
    return ip.is_global


class _Refused(NewConnectionError):
    """Inside urllib3: `_PublicAdapter.send` turns it into `NotPublicAddress`."""

    def __init__(self, conn, host: str) -> None:
        super().__init__(conn, host)
        self.refused_host = host


class _PublicConnectionMixin:
    """Connects only to an address `_is_public` accepts, the one it resolved and checked, while TLS
    still verifies the hostname (urllib3 takes that from the connection's host, not from the socket)."""

    def _new_conn(self):
        try:
            infos = socket.getaddrinfo(self._dns_host, self.port, type=socket.SOCK_STREAM)
        except OSError as e:
            raise NewConnectionError(self, f"Failed to resolve {self.host}: {e}") from e
        addresses = [info[4][0].split("%")[0] for info in infos]
        if not addresses or not all(_is_public(ipaddress.ip_address(a)) for a in addresses):
            raise _Refused(self, self.host)
        last: OSError | None = None
        for address in addresses:
            try:
                return _urllib3_connection.create_connection(
                    (address, self.port), self.timeout, source_address=self.source_address,
                    socket_options=self.socket_options,
                )
            except OSError as e:
                last = e
        raise NewConnectionError(self, f"Failed to establish a new connection: {last}") from last


class _PublicHTTPConnection(_PublicConnectionMixin, HTTPConnection):
    pass


class _PublicHTTPSConnection(_PublicConnectionMixin, HTTPSConnection):
    pass


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicAdapter(HTTPAdapter):
    """Its pools connect only to public addresses (#548). With `system_trust`, HTTPS is verified against the
    operating system's trust store (`truststore`) instead of certifi's bundle: for a site whose root
    certificate certifi does not carry yet. Verification stays on."""

    def __init__(self, *, system_trust: bool = False) -> None:
        self.system_trust = system_trust
        super().__init__()

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        if self.system_trust:
            kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PublicHTTPPool, "https": _PublicHTTPSPool}

    def send(self, request, **kwargs):
        try:
            return super().send(request, **kwargs)
        except requests.exceptions.ConnectionError as e:
            reason = getattr(e.args[0] if e.args else None, "reason", None)
            if isinstance(reason, _Refused):
                raise NotPublicAddress(f"{reason.refused_host} is not a public internet address; it is not fetched") from None
            raise


class RobotsBlocked(Exception):
    """Raised when ``robots.txt`` disallows the requested URL."""

    def __init__(self, url: str) -> None:
        super().__init__(f"robots.txt disallows: {url}")
        self.url = url


def public_session(headers=None, *, system_trust: bool = False) -> requests.Session:
    """A ``requests.Session`` that connects only to public addresses (#548), redirects included, and reads no
    system proxy or .netrc: a proxy resolves the name itself, so the check could not bind to the address it
    connects to."""
    session = requests.Session()
    session.trust_env = False
    session.headers.update(headers if headers is not None else {"User-Agent": USER_AGENT})
    adapter = _PublicAdapter(system_trust=system_trust)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class PoliteSession:
    """A ``requests.Session`` wrapper with jitter, backoff and robots awareness.

    Parameters
    ----------
    min_delay:
        Lower bound of the uniform inter-request sleep (seconds).
    max_delay:
        Upper bound of the uniform inter-request sleep (seconds).
    timeout:
        Default request timeout in seconds (passed to every ``requests.get``): connect and each
        wait for data, so a server trickling bytes can outlast it.
    total_timeout:
        The longest one request may take from sending to its last byte (default ``3 * timeout``,
        #599); also never past the thread's `budget()`.
    max_retries:
        Number of retry attempts on 429 / 5xx before re-raising.
    headers:
        Additional default headers merged into the session.
    obey_robots:
        Whether robots.txt can block a request (default: `OBEY_ROBOTS`).
    system_trust:
        Verify HTTPS against the operating system's trust store rather than certifi's (default off), for a
        site whose root certificate certifi lacks. Verification is never turned off.
    """

    def __init__(
        self,
        *,
        min_delay: float = 0.8,
        max_delay: float = 1.5,
        timeout: float = 20.0,
        total_timeout: float | None = None,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
        obey_robots: bool | None = None,
        system_trust: bool = False,
    ) -> None:
        self.obey_robots = OBEY_ROBOTS if obey_robots is None else obey_robots
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.total_timeout = 3 * timeout if total_timeout is None else total_timeout
        self.max_retries = max_retries
        self.system_trust = system_trust

        # Holds the default headers; each host gets its own copy (`_session_for`).
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        if headers:
            self._session.headers.update(headers)

        # Per host (issue #254): a lock that makes its requests (pause, request,
        # retries) one at a time, and a requests.Session used only under that
        # lock, since a Session is not safe to share between threads.
        self._guard = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._host_sessions: dict[str, requests.Session] = {}

        # robots.txt rules per origin (scheme + host), fetched once per session.
        self._robots_cache: dict[str, robots.Rules] = {}
        self._robots_locks: dict[str, threading.Lock] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _origin(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _host_lock(self, host: str) -> threading.Lock:
        with self._guard:
            return self._host_locks.setdefault(host, threading.Lock())

    def _session_for(self, host: str) -> requests.Session:
        """The host's own ``requests.Session`` (create it on first use). Use it under `_host_lock`."""
        with self._guard:
            if host not in self._host_sessions:
                self._host_sessions[host] = public_session(self._session.headers, system_trust=self.system_trust)
            return self._host_sessions[host]

    def _fetch_robots(self, origin: str) -> robots.Rules:
        """The robots.txt rules for *origin*, as RFC 9309 says to read a fetch:
        2xx is parsed, any other 4xx allows everything, and a 5xx, a 429 (rate
        limited, read as a server error the way Google does) or a failed
        request means the host is unreachable: complete disallow."""
        host = urllib.parse.urlparse(origin).netloc
        try:
            with self._host_lock(host):
                resp = self._send(self._session_for(host), "GET", f"{origin}/robots.txt", None, self.timeout, {})
        except BudgetExceeded:
            raise  # not an answer: nothing is cached, the next employer asks again
        except RequestException:
            return robots.Rules.disallow_all()
        if resp.status_code >= 500 or resp.status_code == 429:
            return robots.Rules.disallow_all()
        if resp.status_code >= 400:
            return robots.Rules.allow_all()
        return robots.parse(resp.text)

    def _rules(self, url: str) -> robots.Rules:
        origin = self._origin(url)
        rules = self._robots_cache.get(origin)
        if rules is None:
            with self._guard:
                lock = self._robots_locks.setdefault(origin, threading.Lock())
            with lock:  # one fetch per origin, however many threads ask at once
                rules = self._robots_cache.get(origin)
                if rules is None:
                    rules = self._robots_cache[origin] = self._fetch_robots(origin)
        return rules

    def _is_allowed(self, url: str) -> bool:
        if not self.obey_robots:
            return True
        return self._rules(url).allowed(robots.path_of(url))

    def allows(self, url: str) -> bool:
        """Whether robots.txt lets door fetch *url* (fetching robots.txt if need be);
        always true when robots.txt is not obeyed."""
        return self._is_allowed(url)

    def ensure_allowed(self, url: str) -> None:
        """Raise `RobotsBlocked` unless robots.txt lets door fetch *url*.

        For the browser scrapers, which load pages outside this session.
        """
        if not self._is_allowed(url):
            raise RobotsBlocked(url)

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """The ``Sitemap:`` URLs in *url*'s host's robots.txt."""
        return self._rules(url).sitemaps

    def disallowed(self, url: str) -> tuple[str, ...]:
        """The ``Disallow:`` paths *url*'s host's robots.txt sets for door (or ``*``)."""
        return tuple(pattern for allow, pattern in self._rules(url).rules if not allow and pattern)

    def crawl_delay(self, url: str) -> float | None:
        """The ``Crawl-delay`` *url*'s host asks of door, if any."""
        return self._rules(url).crawl_delay

    def _parse_retry_after(self, response: requests.Response) -> float | None:
        """Parse the ``Retry-After`` header; return seconds as float or None."""
        value = response.headers.get("Retry-After")
        if not value:
            return None
        # Integer form (number of seconds)
        try:
            return float(value)
        except ValueError:
            pass
        # HTTP-date form
        try:
            import datetime as _dt
            target = parsedate_to_datetime(value)
            now = _dt.datetime.now(_dt.timezone.utc)
            delta = (target - now).total_seconds()
            return max(0.0, delta)
        except Exception:
            return None

    def _backoff_delay(self, attempt: int, response: requests.Response) -> float:
        """Compute backoff duration for a retry *attempt* (0-indexed)."""
        retry_after = self._parse_retry_after(response)
        if retry_after is not None:
            return min(retry_after, _BACKOFF_CAP, MAX_PAUSE_S)
        jitter = random.uniform(0, _BACKOFF_BASE)
        return min(_BACKOFF_BASE ** (attempt + 1) + jitter, _BACKOFF_CAP)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        check_robots: bool = True,
        headers: dict[str, str] | None = None,
        before_redirect: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Fetch *url* paced, with backoff, following redirects by hand.

        Parameters
        ----------
        url:
            Target URL.
        check_robots:
            Consult ``robots.txt`` before fetching *url* and every redirect
            target (it blocks only when the session obeys robots.txt).
        headers:
            Per-call header overrides merged on top of the session defaults.
        before_redirect:
            Called with each redirect target before it is requested; it raises to refuse it.
        **kwargs:
            Forwarded verbatim to ``requests.Session.get``.

        Raises
        ------
        RobotsBlocked
            If the session obeys robots.txt and it disallows *url* or a redirect target.
        requests.exceptions.HTTPError
            For non-retryable 4xx errors or after ``max_retries`` exhausted.
        """
        kwargs.pop("allow_redirects", None)
        params = kwargs.pop("params", None)
        if params:
            # Resolve the query now so robots sees the URL actually requested.
            url = requests.Request("GET", url, params=params).prepare().url
        for _ in range(_MAX_REDIRECTS + 1):
            resp = self._get_once(url, check_robots=check_robots, headers=headers, **kwargs)
            if not resp.is_redirect:
                resp.raise_for_status()
                return resp
            url = urllib.parse.urljoin(resp.url, resp.headers["Location"])
            if before_redirect:
                before_redirect(url)
        raise requests.exceptions.TooManyRedirects(f"more than {_MAX_REDIRECTS} redirects: {url}")

    def redirect_target(self, url: str) -> str | None:
        """Where *url* redirects to (absolute), without following it; None when it does not redirect.
        One request, with the same robots check, pause and backoff as `get`. For short links."""
        resp = self._get_once(url, check_robots=True, headers=None)
        if not resp.is_redirect or not resp.headers.get("Location"):
            return None
        return urllib.parse.urljoin(resp.url, resp.headers["Location"])

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """POST to *url* with the same robots check, pause and backoff as `get`.

        No redirect is followed (an API answers directly); ``json=`` / ``data=``
        are forwarded. Raises `RobotsBlocked` and, on a 4xx/5xx once retries are
        spent, ``requests.exceptions.HTTPError``.
        """
        kwargs.pop("allow_redirects", None)
        resp = self._get_once(url, check_robots=True, headers=headers, method="POST", **kwargs)
        resp.raise_for_status()
        return resp

    def _send(self, session: requests.Session, method: str, url: str, headers: dict[str, str] | None,
              timeout: float, kwargs: dict[str, Any]) -> requests.Response:
        """One attempt with a total deadline (#599): `requests`' timeout is per connect and per wait for
        data, so a host that accepts and then trickles (or stalls between bytes) would hold it for ever.
        The body is read in chunks against the deadline: `total_timeout`, or what the thread's `budget()`
        has left if less. A caller that asks for ``stream=True`` reads the body itself."""
        now = time.monotonic()
        deadline = now + self.total_timeout
        current = getattr(_local, "budget", None)
        budgeted = current is not None and current.deadline < deadline
        if budgeted:
            deadline = current.deadline
        remaining = deadline - now
        if remaining <= 0:
            if budgeted:
                current.hit = True
                raise BudgetExceeded("over its time budget")
            raise requests.exceptions.Timeout(f"no time left for {url}")
        streaming = kwargs.get("stream", False)
        resp = session.request(
            method, url, headers=headers, timeout=min(timeout, remaining), allow_redirects=False,
            **({"stream": True} | kwargs),
        )
        if streaming:
            return resp
        try:
            chunks = []
            size = 0
            # read1 returns what has arrived: a read of N bytes would wait for all N, trickle or not.
            while chunk := resp.raw.read1(65536, decode_content=True):
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise BodyTooLarge(f"{url} is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB")
                if time.monotonic() > deadline:
                    if budgeted:
                        current.hit = True
                        raise BudgetExceeded("over its time budget")
                    raise requests.exceptions.Timeout(f"{url} took more than {self.total_timeout:.0f} s")
        except BaseException:
            resp.close()
            raise
        resp._content = b"".join(chunks)
        resp._content_consumed = True
        return resp

    def _get_once(
        self, url: str, *, check_robots: bool, headers: dict[str, str] | None, method: str = "GET", **kwargs: Any
    ) -> requests.Response:
        """One request, no redirect followed: robots, delay, then retries on 429 / 5xx."""
        if check_robots and not self._is_allowed(url):
            raise RobotsBlocked(url)

        # Merge per-call headers with session defaults.
        merged_headers: dict[str, str] | None = None
        if headers:
            merged_headers = dict(self._session.headers)
            merged_headers.update(headers)

        # Jittered inter-request delay, or the host's Crawl-delay when longer.
        delay = random.uniform(self.min_delay, self.max_delay)
        crawl_delay = self.crawl_delay(url) if check_robots else None
        pause = max(delay, crawl_delay or 0.0)

        timeout = kwargs.pop("timeout", self.timeout)
        host = urllib.parse.urlparse(url).netloc
        session = self._session_for(host)

        # The host's lock is held through the pause, the request and its
        # retries and backoff: one request at a time per host, while other
        # hosts' threads carry on.
        current = getattr(_local, "budget", None)
        lock = self._host_lock(host)
        if current is None:
            lock.acquire()
        elif not lock.acquire(timeout=max(current.deadline - time.monotonic(), 0.0)):
            current.hit = True
            raise BudgetExceeded("over its time budget")
        try:
            _wait(pause)
            for attempt in range(self.max_retries + 1):
                resp = self._send(session, method, url, merged_headers, timeout, kwargs)
                status = resp.status_code
                retryable = status == 429 or status >= 500
                if not retryable or attempt >= self.max_retries:
                    return resp
                _wait(self._backoff_delay(attempt, resp))
        finally:
            lock.release()

        # Unreachable — the loop always returns.
        raise RuntimeError("PoliteSession.get: unexpected loop exit")
