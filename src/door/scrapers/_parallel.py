"""Run a per-company feed's entries side by side, one host at a time (issue #254).

The entries of a feed (career sites, SuccessFactors hosts, Teamtailor boards,
...) each live on some host. Requests to one host stay one at a time with
`PoliteSession`'s pause between them, but requests to different hosts need not
wait on each other. `map_by_group` runs the entries on a small thread pool,
all the entries of one host in order on one worker, and returns the results in
the order of the entries, so the output never depends on timing.

Hosts on one provider's domain (every ``*.myworkdayjobs.com`` tenant, every
``*.teamtailor.com`` board) run side by side too, but at most `PER_PROVIDER`
at once, so the provider never sees a burst from the whole pool.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import TypeVar
from urllib.parse import urlparse

from door.core import progress

DEFAULT_WORKERS = 8  # `scrape_workers` when the profile does not set it
PER_PROVIDER = 4  # hosts of one provider's domain fetched at once

T = TypeVar("T")
R = TypeVar("R")


def workers(config: dict) -> int:
    """The pool size the profile asks for (`scrape_workers`; 1 = fully serial)."""
    value = config.get("scrape_workers")
    return DEFAULT_WORKERS if value is None else int(value)


def host_of(url_or_host: str) -> str:
    """The whole host of a URL or host, lower-cased: an entry's queue. Pure."""
    parsed = urlparse(url_or_host if "//" in url_or_host else f"//{url_or_host}")
    return (parsed.hostname or url_or_host).lower()


def host_group(url_or_host: str) -> str:
    """The provider a host belongs to: its last two labels (``a.teamtailor.com`` and
    ``b.teamtailor.com`` both ``teamtailor.com``); `PER_PROVIDER` caps how many of
    its hosts run at once. Pure."""
    parsed = urlparse(url_or_host if "//" in url_or_host else f"//{url_or_host}")
    host = (parsed.hostname or url_or_host).lower()
    return ".".join(host.split(".")[-2:])


def map_by_group(
    entries: Sequence[T], group_of: Callable[[T], str], fn: Callable[[T], R], max_workers: int,
    *, per_provider: int | None = None, on_result: Callable[[int, R], None] | None = None,
) -> list[R]:
    """``[fn(e) for e in entries]``, with different groups running concurrently.

    Entries sharing ``group_of(entry)`` (a host) run in their given order on one thread;
    at most *per_provider* (default `PER_PROVIDER`) groups whose `host_group` is the
    same run at once. Results are in the order of *entries*. With ``max_workers`` of 1 (or one
    group) it is the plain loop on the calling thread. The first exception in
    entry order is raised, after every group has finished. The calling
    thread's progress scope (the site) carries over to the workers.

    *on_result*, when given, hears ``(index, result)`` as each entry finishes, always on the calling
    thread (so it may write files), whichever worker produced it.
    """
    groups: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        groups.setdefault(group_of(entry), []).append(index)

    def tracked_fn(entry: T) -> R:
        """``fn(entry)``, reported as started and ended under the entry's group (its host)."""
        label = group_of(entry)
        progress.report(label, stage="entry_start")
        try:
            return fn(entry)
        finally:
            progress.report(label, stage="entry_end")

    if max_workers <= 1 or len(groups) <= 1:
        out = []
        for index, entry in enumerate(entries):
            out.append(tracked_fn(entry))
            if on_result is not None:
                on_result(index, out[-1])
        return out

    cap = max(PER_PROVIDER if per_provider is None else per_provider, 1)
    pool_size = min(max_workers, len(groups))
    scope = progress.current_scope()
    results: list = [None] * len(entries)
    errors: dict[int, BaseException] = {}
    lock = threading.Lock()
    outbox: queue.Queue = queue.Queue()

    def run_group(indices: list[int]) -> None:
        with progress.scope(**scope):
            for index in indices:
                try:
                    results[index] = tracked_fn(entries[index])
                    outbox.put((index, results[index]))
                except Exception as exc:  # noqa: BLE001 - re-raised below, in entry order
                    with lock:
                        errors[index] = exc

    # Start a host's queue only when the pool has a free worker and its provider is
    # under the cap, so a worker never sits blocked while another host could run.
    pending = list(groups.items())
    active: dict[str, int] = {}
    running: dict = {}

    def hear() -> None:
        while on_result is not None:
            try:
                index, result = outbox.get_nowait()
            except queue.Empty:
                return
            on_result(index, result)

    with ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="feed") as pool:
        try:
            while pending or running:
                waiting = []
                for key, indices in pending:
                    provider = host_group(key)
                    if len(running) < pool_size and active.get(provider, 0) < cap:
                        active[provider] = active.get(provider, 0) + 1
                        running[pool.submit(run_group, indices)] = provider
                    else:
                        waiting.append((key, indices))
                pending = waiting
                done, _ = wait(running, timeout=0.2, return_when=FIRST_COMPLETED)
                hear()
                for future in done:
                    active[running.pop(future)] -= 1
                    future.result()
        finally:
            hear()

    if errors:
        raise errors[min(errors)]
    return results
