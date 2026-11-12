"""Step 3, `follow`: find each queued employer's own job feed, and record the result.

Every employer in the candidates queue (`jobs/candidates.json`) that `profile/companies.json`
does not already settle (followed, or found unfollowable or unresolved less than 90 days ago) is
run through the detection of `door.commands.companies._classify`: the shape of its links, the
DNS name of its career host, its careers page and the pages that links to, and for a name its
likely slugs on each feed, then its own website as Wikidata names it (`door.core.wikidata`, one lookup
per name a run, shared by all employers: `companies.Context.employers`) (all with a polite session,
probing on). The verdict
is recorded in companies.json at once: ``followed`` (with the feed), ``unfollowable`` (a
platform whose terms rule it out) or ``unresolved`` (with the reason), ``found_via`` the source
that queued it. Recorded employers leave the queue; entries not seen for ``max_age_days`` are
dropped. A LinkedIn employer with no apply link yet is tried by its name first (the name probe with
its same-name confirmation, then the model); when that finds no feed it is *parked*: marked
``name_tried`` and left queued as "waiting for an apply link" for `discover` to read its job page,
which costs a LinkedIn request.

The detection runs in parallel, one queue per host and at most `PER_PROVIDER` hosts of one
provider at once (`door.scrapers._parallel`); the session's own pacing (0.3 to 0.6 s per
host) stays. ``dry_run`` prints what would be recorded and writes nothing.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime, timezone
from pathlib import Path

from door import pipeline
from door.commands import _common as common
from door.commands import companies as companies_cmd
from door.core import ats_detect, candidates, careers_ai, sites, wikidata, workspace
from door.core import companies as store
from door.core import progress as progress_mod
from door.scrapers import _parallel, http_client
from door.scrapers.feeds import hr_manager

_NO_FEED = "no job feed found"
# The longest one employer's checks may take (pauses and requests together): past it follow records an error
# for that employer and goes on (#545).
EMPLOYER_BUDGET_S = 180.0
_SAVE_EVERY = 10      # results recorded between two saves of companies.json and the queue
_SAVE_SECONDS = 5.0  # ... or this long


def _external(entry: dict) -> list[str]:
    return [l for l in entry["links"] if not ats_detect.is_job_board(l)]


def _group(entry: dict) -> str:
    """The queue an employer's detection runs in: the host of its first employer link, else its first link."""
    if not _external(entry) and candidates.needs_apply_link(entry):
        return entry["name"].lower()  # a LinkedIn employer is checked by name: no host to pace
    links = _external(entry) or entry["links"]
    return _parallel.host_of(links[0]) if links else entry["name"].lower()


def _company(entry: dict) -> dict:
    """The queue entry in the shape `companies._classify` reads."""
    via = next((s for s in entry["sources"] if s in store.found_via_values() and s != "manual"), "manual")
    return {"company": entry["name"], "links": entry["links"], "postings": max(len(entry["titles"]), 1),
            "titles": list(entry["titles"]), "sources": set(entry["sources"]), "via": via}


def _dormant(items: list[store.Company], entry: dict) -> store.Company | None:
    """The dormant employer with a known feed that a queued *entry* is (it was seen with a fitting ad), else None."""
    company = store.find(items, entry["name"])
    return company if company is not None and company.status == "dormant" and company.feed is not None else None


def _refollow(entry: dict, company: store.Company) -> dict:
    """The result row of a dormant employer followed again on the feed it kept: no detection."""
    evidence = f"followed again: a fitting job was seen ({company.feed.platform}:{company.feed.id} unchanged)"
    return {"company": company.name, "status": "followed", "platform": company.feed.platform,
            "entry": company.feed.id, "config_key": sites.FEED_SITES[company.feed.platform],
            "evidence": evidence, "reason": None, "postings": max(len(entry["titles"]), 1), "links": entry["links"],
            "external": _external(entry), "found_via": company.found_via, "error": None}


def _links_name_shared(entry: dict) -> bool:
    """Whether a queued employer's links carry the customer number of a shared feed (the state portal)."""
    return any(hr_manager.shared_alias_for_cid(hr_manager.hr_manager_cid(l)) for l in entry["links"])


def _held(items: list[store.Company], entry: dict, now: datetime) -> bool:
    """Whether the list settles a queued employer: followed, or looked at less than 90 days ago. Not an
    unresolved agency whose links name a shared feed: its customer number now resolves it."""
    if not store.is_settled(items, entry["name"], now):
        return False
    company = store.find(items, entry["name"])
    return not (company is not None and company.status != "followed" and _links_name_shared(entry))


def _shared_feed(row: dict) -> tuple[str, str] | None:
    """The feed a followed row lands on when several employers share it, else None."""
    if row["status"] == "followed" and row["platform"] and store.shared_name(row["platform"], row["entry"]):
        return row["platform"], row["entry"]
    return None


def _verdict(entry: dict, found: tuple[str, dict] | None) -> dict:
    """One employer's result row from what `_classify` said (None: nothing found)."""
    company = _company(entry)
    row = {"company": entry["name"], "status": "unresolved", "platform": None, "entry": None, "config_key": None,
           "evidence": None, "refusal": None, "reason": _NO_FEED, "postings": company["postings"], "links": entry["links"],
           "external": _external(entry), "found_via": company["via"], "error": None}
    if found is None:
        if not row["external"]:
            row["reason"] = f"{_NO_FEED} (no employer link in its postings)"
        return row
    kind, item = found
    if kind == "suggestions" and str(item.get("evidence") or "").startswith("ai:"):
        row["found_via"] = "ai"
    if kind == "unresolved":
        row["reason"] = item.get("reason") or row["reason"]
        row["retry"] = bool(item.get("retry"))
    elif kind == "suggestions":
        row.update(status="followed", platform=item["platform"], entry=item["entry"], config_key=item["config_key"],
                   evidence=item["evidence"], reason=None)
    elif kind == "unfollowable":
        row.update(status="unfollowable", platform=item["platform"], evidence=item["evidence"], reason=item["evidence"],
                   refusal=item.get("refusal"))
    return row


def _retry(row: dict) -> bool:
    """An employer whose only missing answer was Wikidata's, which was not asked (it stopped answering or the
    run's budget was spent): not recorded, so it is not settled for 90 days and a later run asks again."""
    return row["status"] == "unresolved" and bool(row.get("retry")) and not row["error"]


def _parked(entry: dict | None, row: dict) -> bool:
    """A LinkedIn employer with no apply link whose name found no feed: it waits for its job page
    rather than being recorded as unresolved."""
    return entry is not None and row["status"] == "unresolved" and not row["error"] and candidates.needs_apply_link(entry)


def _summary(block: dict) -> str:
    parts = []
    if block["checked"]:
        parts.append(f"{block['checked']} candidates: {len(block['followed'])} followed, "
                     f"{len(block['unfollowable'])} unfollowable, {len(block['unresolved'])} unresolved")
        if block["errors"]:
            parts.append(f"{len(block['errors'])} failed")
    else:
        parts.append("nothing to check")
    if block["kept"]:
        parts.append(f"{block['kept']} waiting for an apply link")
    return ("would record " if block["dry_run"] and block["checked"] else "") + ", ".join(parts)


@common._locked("follow")
def _follow_core(
    *, dry_run: bool = False, probe: bool = True, late: bool = False, jobs_dir: Path | None = None,
    profile_dir: Path | None = None, progress=None,
) -> dict:
    """Detect the feed of every queued employer and record the result. Never prints.

    Args:
        dry_run: Detect, but write neither companies.json nor the queue.
        probe: Read DNS and pages and probe feeds (the real thing); False looks at the links' shape
            only (for tests).
        late: A second pass over the employers `discover` queued while the first ran (`find`'s
            "late follow"): its progress events are ``late`` events, folded into the step's line.

    Returns:
        ``{"step": "follow", "dry_run", "queued", "checked", "followed": [{"company", "platform",
        "entry"}], "unfollowable": [{"company", "reason"}], "unresolved": [{"company", "reason"}],
        "kept", "settled", "expired", "errors": [{"company", "error"}], "results": [<one row per
        employer checked: company, status, platform, entry, config_key, evidence, reason, postings,
        links, external, found_via>], "elapsed_s", "summary"}`` — ``kept`` waits in the queue for an
        apply link (parked after a name attempt) or for a later run's Wikidata lookup (it was not asked: it stopped answering or
        the run's budget was spent; the employer is not recorded as unresolved), ``settled`` were already on the list (or are one more agency of a
        shared feed, e.g. the state's recruiting portal, which is followed once), ``expired`` were not seen for
        ``max_age_days``.

    Raises:
        ConfigError / FileNotFoundError: the profile config or companies.json is invalid or missing.
    """
    jobs_dir = workspace.JOBS_DIR if jobs_dir is None else jobs_dir
    profile_dir = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    config = common._load_config(profile_dir)
    now = datetime.now(timezone.utc)
    started = time.monotonic()

    queue = candidates.load(jobs_dir)
    items = common._company_items(profile_dir)
    block = {"step": "follow", "dry_run": dry_run, "queued": len(queue), "checked": 0, "followed": [],
             "unfollowable": [], "unresolved": [], "kept": 0, "settled": 0, "expired": 0, "errors": [],
             "results": [], "elapsed_s": 0.0, "summary": ""}
    expired = candidates.expire(queue, config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS), now)
    block["expired"] = len(expired)
    settled = [k for k, e in queue.items() if _held(items, e, now)]
    block["settled"] = len(settled)
    for key in settled:
        del queue[key]
    again = {k: c for k, e in queue.items() if (c := _dormant(items, e)) is not None}
    waiting = [k for k, e in queue.items() if candidates.awaiting_job_page(e) and k not in again]
    block["kept"] = len(waiting)
    todo = {k: e for k, e in queue.items() if k not in waiting}

    recorded: set[str] = set()
    # Feeds shared by several employers (the state portal): followed once, however many agencies lead to it.
    shared_seen = {(c.feed.platform, c.feed.id) for c in items
                   if c.status == "followed" and c.feed and store.shared_name(c.feed.platform, c.feed.id)}
    batch = {"n": 0, "at": time.monotonic()}

    def flush() -> None:
        store.save(profile_dir, items)
        candidates.save(jobs_dir, queue)
        batch.update(n=0, at=time.monotonic())

    def record(key: str, row: dict) -> None:
        """Record one employer's result and dequeue it at once (saved every few results or seconds), so an
        interruption loses only the last few."""
        if dry_run or row["error"] or key in recorded:
            return
        if _retry(row):
            recorded.add(key)
            return
        if _parked(queue.get(key), row):
            candidates.mark_name_tried(queue[key], now)
            recorded.add(key)
            batch["n"] += 1
            return
        store.record(items, row["company"], feed=(row["platform"], row["entry"]) if row["entry"] else None,
                     status=row["status"], found_via=row["found_via"], reason=row["reason"],
                     evidence=row["evidence"], now=store.now_iso(), refusal=row.get("refusal"))
        queue.pop(key, None)
        recorded.add(key)
        batch["n"] += 1
        if batch["n"] >= _SAVE_EVERY or time.monotonic() - batch["at"] >= _SAVE_SECONDS:
            flush()

    with pipeline.running("follow", total=len(todo), late=late) as step:
        try:
            fresh = [(k, e) for k, e in todo.items() if k not in again]
            for key, company in again.items():
                record(key, _refollow(todo[key], company))
            detected = iter(_detect(fresh, config, probe, items, on_row=record))
            rows = [_refollow(e, again[k]) if k in again else next(detected) for k, e in todo.items()]
        finally:
            if not dry_run and batch["n"]:
                flush()
        for (key, entry), row in zip(todo.items(), rows):
            block["results"].append(row)
            if row["error"]:
                block["errors"].append({"company": entry["name"], "error": row["error"]})
                continue
            if _retry(row) or _parked(entry, row):
                block["kept"] += 1  # not recorded: it waits for discover to read its job page
                record(key, row)
                continue
            bucket = {"followed": "followed", "unfollowable": "unfollowable"}.get(row["status"], "unresolved")
            summary = {"company": row["company"]}
            shared = _shared_feed(row)
            if shared is not None and shared in shared_seen:
                block["settled"] += 1  # the shared feed is followed (or about to be): one more agency leading to it
                record(key, row)
                continue
            if shared is not None:
                shared_seen.add(shared)
            if bucket == "followed":
                summary.update(platform=row["platform"], entry=row["entry"])
            else:
                summary["reason"] = row["reason"]
            block[bucket].append(summary)
            record(key, row)
        block["checked"] = len(todo)
        if not dry_run:
            flush()
        block["summary"] = step.summary = _summary(block)
    block["elapsed_s"] = time.monotonic() - started
    return block


def _detect(
    entries: list[tuple[str, dict]], config: dict, probe: bool, items: list[store.Company], on_row=None,
) -> list[dict]:
    """The result row of every ``(key, entry)``, detected in parallel: one queue per host, at most
    `PER_PROVIDER` hosts of one provider at once. An unexpected error becomes the row's ``error``.
    *on_row*, when given, hears ``(key, row)`` as soon as an employer's result is final (on the calling thread)."""
    session = companies_cmd._session() if probe else None
    ctx = companies_cmd.Context(
        hr_aliases=tuple(c.feed.id for c in items if c.status == "followed" and c.feed and c.feed.platform == "hr_manager"),
        places=tuple(ats_detect.places_for(str(config.get("location") or ""))),
        hosts=companies_cmd._host_guesses(str(config.get("location") or "")),
        site_labels=companies_cmd._site_labels(str(config.get("location") or "")),
        employers=wikidata.Lookup(str(config.get("location") or "")) if probe else None,
    )
    ask = None
    if probe and config.get("follow_ai_fallback", True):
        location = str(config.get("location") or "")
        ask = lambda company: careers_ai.ask_careers_url(  # noqa: E731
            company["company"], (company.get("titles") or [None])[0], location)
    lock = threading.Lock()
    done = [0]
    total = len(entries)
    wanted: set[str] = set()   # employers whose every Python check failed: the model is asked later
    answers: dict[str, str | None] = {}
    final = [False]

    def defer(company: dict) -> str | None:
        if final[0]:
            return answers.get(company["company"])
        with lock:
            wanted.add(company["company"])
        return None

    ctx.ai = defer if ask is not None else None

    def check(item: tuple[str, dict]) -> dict:
        entry = item[1]
        try:
            with http_client.budget(EMPLOYER_BUDGET_S) as spent:
                found = companies_cmd._classify(session, _company(entry), set(), ctx)
            row = _verdict(entry, found)
            if spent.hit:  # its checks were cut short: no verdict is better than a wrong one
                row = {**_verdict(entry, None), "error": f"over its time budget ({EMPLOYER_BUDGET_S:.0f} s): left for the next run"}
        except Exception as exc:  # noqa: BLE001 - one employer's failure must not stop the others
            row = {**_verdict(entry, None), "error": f"{type(exc).__name__}: {exc}"}
        with lock:
            if entry["name"] in wanted and not final[0]:
                return row  # reported once the model has answered
            done[0] += 1
            progress_mod.report("checking", done[0], total, stage="candidate")
        return row

    workers = _parallel.workers(config)
    def heard(index: int, row: dict) -> None:
        if on_row is not None and not (entries[index][1]["name"] in wanted and not final[0]):
            on_row(entries[index][0], row)

    rows = _parallel.map_by_group(entries, lambda item: _group(item[1]), check, workers, on_result=heard)
    asked = [(i, item) for i, item in enumerate(entries) if item[1]["name"] in wanted]
    if not asked:
        return rows

    def question(pair: tuple[int, tuple[str, dict]]) -> None:
        entry = pair[1][1]
        try:
            answers[entry["name"]] = ask(_company(entry))
        except Exception:  # noqa: BLE001 - a failed question is no answer
            answers[entry["name"]] = None

    with ThreadPoolExecutor(max_workers=careers_ai.MAX_PARALLEL) as pool:
        list(pool.map(question, asked))
    final[0] = True
    # No answer: the first result stands (and its notes); an answer is fed back into the same checks.
    answered = [(i, item) for i, item in asked if answers.get(item[1]["name"])]
    again = _parallel.map_by_group(
        [item for _, item in answered], lambda item: _group(item[1]), check, workers,
        on_result=lambda n, row: heard(answered[n][0], row))
    for (i, _), row in zip(answered, again):
        rows[i] = row
    for i, item in asked:
        if not answers.get(item[1]["name"]):
            heard(i, rows[i])
    unanswered = len(asked) - len(answered)
    with lock:
        for _ in range(unanswered):
            done[0] += 1
            progress_mod.report("checking", done[0], total, stage="candidate")
    return rows
