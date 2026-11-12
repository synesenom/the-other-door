"""The scraping engine behind `search` and `collect`: drive a list of sites (the boards, or
the platforms of the followed employers), write their new postings, keep the per-site outcomes,
watermarks, resting and history, and run the passes (liveness, prefilter, dedup, language,
condense, prescreen) over what was written. `door.pipeline.search` and `.collect` call
`_scrape_core` with their own site lists; the match step runs the passes (`_scrape_passes`)."""

import json
import queue
import re
import threading
from pathlib import Path

from door.commands import _common as common
from door import i18n
from door.core import progress as progress_mod
from door.core import models, sites, workspace
from door.core import freshness
from door.core import companies as companies_store
from door.core.sites import FEED_SITES, SITES
from door.matching import integrity, title_fit
from door.scrapers import _parallel
from door.scrapers import drain_entry_errors as _drain_scraper_entry_errors
from door.scrapers import drain_errors as _drain_scraper_errors
from door.scrapers import drain_answered as _drain_scraper_answered
from door.scrapers import drain_non_local as _drain_scraper_non_local
from door.scrapers import drain_pushback as _drain_scraper_pushback


class _SiteRun:
    """One site's scrape as the consuming thread sees it: the scraper's records go through
    `accept`, which filters them against history and writes the new ones to disk, and the
    counters say how it went. Only the thread that runs `_scrape_core` calls `accept`.

    *topic* (collect only: `title_fit.topic_terms`) drops a new posting whose title holds none of
    the terms: an employer's feed lists all its jobs, the keywords only a few. It is remembered in
    history, so it is never checked again, and counted in `off_topic`."""

    def __init__(self, index, site, scraper, store, known_ids, out_dir, cutoff, max_postings,
                 recheck_after_days, candidates_paths, freshness, topic=None):
        self.index, self.site, self.scraper, self.store = index, site, scraper, store
        self.known_ids, self.out_dir, self.cutoff = known_ids, out_dir, cutoff
        self.max_postings, self.recheck_after_days = max_postings, recheck_after_days
        self.candidates_paths, self.freshness, self.topic = candidates_paths, freshness, topic
        self.count = 0
        self.off_topic = 0
        self.stale = 0
        self.seen = 0  # every record the scraper returned: new, known or too old
        self.capped = False
        self.failure: BaseException | None = None  # a write that failed in `accept`
        self.cancelled = threading.Event()  # tells the producing thread to stop
        self._streams = getattr(scraper, "iter_scrape", None) is not None

    def records(self, config: dict):
        """The scraper's records, one by one: an `iter_scrape` generator lazily (so a
        site persists incrementally), a plain `scrape` list in one go."""
        if self._streams:
            yield from self.scraper.iter_scrape(config, known_ids=self.known_ids, since=self.cutoff)
        else:
            yield from self.scraper.scrape(config, known_ids=self.known_ids, since=self.cutoff)

    def accept(self, record: dict) -> None:
        """Count one record; write it unless it is a known id or too old. Sets `capped`
        (and `cancelled`) once `max_postings_per_site` postings are written."""
        self.seen += 1
        if self._streams and record.get("seen_only"):
            pid = record.get("platform_id")
            if pid:
                self.store.touch(models.make_job_id(self.site, pid))
            return
        self._write_posting(record)
        if self.max_postings is not None and self.count >= self.max_postings:
            self.capped = True
            self.cancelled.set()

    def _write_posting(self, posting: dict) -> None:
        """Filter against history (safety net: `known_ids` was a point-in-time snapshot)
        and, if genuinely new, write it to disk and history at once so progress survives
        a mid-run interruption."""
        if self.freshness.is_stale(posting, self.cutoff):
            self.stale += 1
            return
        pid = posting.get("platform_id")
        job_id = posting["id"]
        if pid and not self.store.is_new(job_id, self.site, self.recheck_after_days):
            self.store.touch(job_id)
            return
        if posting.get("title"):  # every board and feed posting is written here: drop a gender tag ("H/F") once
            posting["title"] = i18n.strip_title_tags(str(posting["title"]))
        if self.topic and not title_fit.on_topic(str(posting.get("title") or ""), self.topic):
            if pid:
                self.store.record(job_id, pid, posting.get("url", ""), self.site)
            self.off_topic += 1
            return
        integrity.apply(posting)
        posting_path = self.out_dir / f"{posting['id']}.json"
        with posting_path.open("w") as f:
            json.dump(posting, f, indent=2, default=str)
        self.candidates_paths.append(posting_path)
        if pid:
            self.store.record(job_id, pid, posting.get("url", ""), self.site)
        self.count += 1
        if self.count % 5 == 0:
            progress_mod.report("postings", self.count, site=self.site, stage="postings")
        # Periodic checkpoint so a long-running site doesn't lose
        # everything if interrupted between explicit saves.
        if self.count % 10 == 0:
            self.store.save()


@common._locked("scrape")
def _scrape_core(
    site_list: list[str] | None,
    jobs_dir: Path | None = None,
    profile_dir: Path | None = None,
    *,
    mode: str = "search",
    companies: list[str] | None = None,
    passes: bool = True,
    progress=None,
) -> dict:
    """Scrape a list of sites, write their new postings, run the passes; return structured data.

    The engine of `search` (``mode="search"``: the boards, with the profile's keywords) and
    `collect` (``mode="collect"``: the platforms of the employers followed in
    `profile/companies.json`). Loads `profile/config.json`,
    imports each site's module (`door.core.sites.SITES`), writes new postings to
    `jobs_dir/<run_date>/<site>/`, updates the cross-run `HistoryStore`, then
    runs the optional liveness check and, with ``passes``, `matching.prefilter`, `matching.dedup`,
    `matching.language`, `matching.condense` and `matching.prescreen`
    but never prints —
    callers (CLI, MCP) render their own presentation from the returned dict.

    Freshness differs by mode. A board posting is new when it was published since the site's
    last successful scrape (minus a day, at most `max_age_days` back). An employer's feed posting
    is new when The other door has not seen it before (the history), whatever its ``posted_at``.

    Args:
        site_list: Explicit site names to scrape, or `None`/empty for the default: every board of
            the profile's country (search), or the platforms with a followed employer (collect).
        mode: ``"search"`` or ``"collect"``.
        companies: Collect only: scrape just these followed employers (names on the list).
        passes: Run the passes over `jobs_dir/<run_date>/` afterwards (the pipeline runs them
            once, in the match step, and passes False here).
        jobs_dir: Root directory for scraped postings (defaults to the
            module-level `JOBS_DIR`).
        profile_dir: Directory containing `config.json` (defaults to the
            module-level `PROFILE_DIR`).

    A board keeps postings since its last successful scrape, minus a day, never more than
    `max_age_days` ago (`door.core.freshness`); older ones are skipped (not written, not
    recorded in history) and counted as ``stale``. The cutoff is also passed to the scraper as
    ``since=`` so one that can filter at the source does. A site's watermark only advances after
    a scrape that completed without failing or hitting the cap.
        progress: A `door.core.progress.Reporter` (or None) that receives
            `Progress` events while the call runs: "scraping (site i/N)" when
            a site starts (i is its place in the list; with `scrape_workers` above 1
            several run at once) and one closing event per site, counting the
            sites finished so far, whatever the scrapers report, then one
            event per pass. The core still never prints.

    Returns:
        ``{"run_date", "mode", "employers", "written", "sites": [{"site", "outcome": "ok"|
        "not_implemented"|"not_configured"|"reserved"|"resting"|"error"|"failed"|"empty",
        "count"?, "stale"?, "non_local"?, "since"?, "dir"?, "config_key"?, "terms_url"?, "until"?, "error"?, "errors"?,
        "warning"?}, ...], "liveness": None |
        {"before", "after"}, "prefilter": None | {"available": False} |
        {"available": True, "survived"}, "dedup": None |
        {"available": False} | {"available": True, "collapsed",
        "remaining"}, "condense": None | {"available": False} |
        {"available": True, "count", "ratio_pct"}, "language": None |
        {"languages": {code|"unknown": n}, "dropped", "translated", "failed_batches"},
        "prescreen": None |
        {"available": False} | {"available": True, "scored", "kept"},
        "candidates_dir", "surviving_paths"}``.

    Raises:
        FileNotFoundError: `profile_dir/config.json` is missing.
        ConfigError: `profile_dir/config.json` fails validation (issue #137).
        ValueError: `site_list` (or the configured fallback) names an
            unknown site, or `companies` names an employer that is not
            followed.
    """
    from datetime import datetime, timezone

    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR

    # The scrapers stay stateless and keep reading their old key names; the employer list
    # (profile/companies.json) is where those entries now live, merged in here.
    if mode not in ("search", "collect"):
        raise ValueError(f"unknown mode {mode!r} (search or collect)")
    collecting = mode == "collect"
    config = {**common._load_config(profile_dir), "_mode": mode}
    # The profile's country (lowercase ISO code, or None) is resolved once for every scraper.
    country = i18n.country_for_location(config.get("location") or "")
    config["_country"] = country.code.lower() if country is not None else None
    if collecting:
        config.update(_feed_config_for(profile_dir, companies))
        # Each followed employer's name, so a scraper labels its postings with it, not the feed's guess.
        config["_names"] = companies_store.feed_names(_followed_for(profile_dir, companies))
    scrape_started = datetime.now(timezone.utc)
    scrape_state = freshness.load_scrape_state(jobs_dir)
    max_age_days = config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS)

    if site_list:
        resolved_sites = list(site_list)
    elif collecting:
        resolved_sites = [s for s, key in FEED_SITES.items() if config.get(key)]
    else:
        resolved_sites = sites.boards_for_location(config.get("location", ""))

    unknown = [s for s in resolved_sites if s not in SITES]
    if unknown:
        raise ValueError(f"unknown site(s): {', '.join(unknown)}. Valid sites: {', '.join(SITES)}")

    from datetime import date
    run_date = date.today().isoformat()

    from door.core.history import HistoryStore
    store = HistoryStore(jobs_dir / "history.json")
    recheck_after_days = config.get("recheck_after_days", None)

    candidates_paths: list = []
    topic = title_fit.topic_terms(config) if collecting else None
    results: dict[int, dict] = {}  # by position in `resolved_sites`
    n_sites = len(resolved_sites)
    finished = 0  # sites done or skipped so far, for the "i/N" counter
    pool_size = _parallel.workers(config)

    def _finish_site(index: int, entry: dict) -> None:
        """Record the site's result and report that the site is done."""
        nonlocal finished
        results[index] = entry
        finished += 1
        progress_mod.report(
            _site_done_message(entry), finished, n_sites,
            site=entry["site"], stage="scrape", outcome=entry["outcome"],
        )

    def _start_site(index: int, site: str) -> "_SiteRun | None":
        """Skip, or set up, one site; `None` when it will not be scraped."""
        nonlocal finished
        held_back = _held_back(site, scrape_state, scrape_started)
        if held_back is not None:
            results[index] = held_back
            finished += 1
            return None
        config_key = SITES[site].config_key
        if collecting and config_key and not config.get(config_key):
            # A per-company feed with no companies listed has nothing to
            # fetch: skip it quietly instead of flagging an "empty" site.
            results[index] = {"site": site, "outcome": "not_configured", "config_key": config_key}
            finished += 1
            return None
        try:
            scraper = __import__(SITES[site].module, fromlist=["scrape"])
            out_dir = workspace.day_dir(jobs_dir, run_date) / site
            out_dir.mkdir(parents=True, exist_ok=True)
            return _SiteRun(
                index, site, scraper, store, store.known_ids(site, recheck_after_days), out_dir,
                _cutoff(site, collecting, scrape_state, max_age_days, scrape_started),
                config.get("max_postings_per_site"), recheck_after_days, candidates_paths, freshness,
                topic=topic,
            )
        except ImportError:
            _finish_site(index, {"site": site, "outcome": "not_implemented"})
        except Exception as exc:
            _finish_site(index, {"site": site, "outcome": "error", "error": str(exc)})
        return None

    def _finish_run(run: "_SiteRun", failure: BaseException | None) -> None:
        """A site's scraper is done (or raised): close its books and report its outcome."""
        # Always persist whatever was written so far, even if the scraper raised
        # partway through (issue #134).
        store.save()
        failure = failure or run.failure
        # Drain this site's own errors (issue #132) so they never leak into
        # another site's outcome, whatever runs beside it.
        site_errors = _drain_scraper_errors(run.site).get(run.site, [])
        entry_errors = _drain_scraper_entry_errors(run.site)
        non_local = _drain_scraper_non_local(run.site)
        answered = _drain_scraper_answered(run.site)
        if _drain_scraper_pushback(run.site):
            freshness.record_pushback(jobs_dir, run.site, datetime.now(timezone.utc))
        if isinstance(failure, ImportError):
            _finish_site(run.index, {"site": run.site, "outcome": "not_implemented"})
            return
        if failure is not None:
            _finish_site(run.index, {"site": run.site, "outcome": "error", "error": str(failure)})
            return

        # count == 0 with recorded errors -> a broken scraper masquerading
        # as a quiet day ("failed"). No errors and not a single record,
        # not even a known or too-old one -> suspicious ("empty"): the
        # site may have changed under the scraper. Only known/old records
        # -> genuinely nothing new ("ok"). A site with count > 0 is never
        # downgraded, even if some requests also failed (partial success). A site
        # that read a recognised results page with no hits (`record_answered`) is a
        # quiet day ("ok") too.
        if run.count == 0 and site_errors:
            outcome = "failed"
        elif run.seen == 0 and not answered:
            outcome = "empty"
        else:
            outcome = "ok"
        # Only a complete, clean scrape moves the watermark: after a
        # failure or a capped run, next time must look as far back again.
        if outcome == "ok" and not site_errors and not run.capped and not collecting:
            freshness.record_scrape(jobs_dir, run.site, scrape_started)
        entry = {
            "site": run.site, "outcome": outcome, "count": run.count, "stale": run.stale,
            "since": run.cutoff.isoformat() if run.cutoff else None, "dir": str(run.out_dir),
            "errors": site_errors,
        }
        if entry_errors:
            entry["entry_errors"] = entry_errors  # {feed entry: {"outcome", "reason"}}, for `collect` to stamp
        if non_local:
            entry["non_local"] = non_local
        if run.off_topic:
            entry["off_topic"] = run.off_topic
        if outcome == "empty":
            entry["warning"] = _empty_site_warning(SITES[run.site], config)
        progress_mod.report("postings", run.count, site=run.site, stage="postings")  # the final count
        _finish_site(run.index, entry)

    def _announce(run: "_SiteRun") -> None:
        progress_mod.report(f"scraping (site {run.index + 1}/{n_sites})", site=run.site, stage="scrape")

    def _run_inline(run: "_SiteRun") -> None:
        """Scrape, write and finish one site on this thread."""
        _announce(run)
        failure: BaseException | None = None
        with progress_mod.scope(site=run.site, stage="scrape"):
            try:
                for record in run.records(config):
                    run.accept(record)
                    if run.capped:
                        break
            except Exception as exc:
                failure = exc
        _finish_run(run, failure)

    if pool_size <= 1:
        # One site after another on this thread, exactly as before concurrency.
        for index, site in enumerate(resolved_sites):
            run = _start_site(index, site)
            if run is not None:
                _run_inline(run)
    else:
        runs = [run for index, site in enumerate(resolved_sites) if (run := _start_site(index, site))]
        pooled = runs
        inbox: queue.Queue = queue.Queue(maxsize=16)  # a streaming site cannot run far ahead of its writes
        tasks: queue.Queue = queue.Queue()
        for r in pooled:
            tasks.put(r)

        def _work() -> None:
            """A pool thread: scrape sites off `tasks`, hand every record to `inbox`."""
            while True:
                try:
                    run = tasks.get_nowait()
                except queue.Empty:
                    return
                failure: BaseException | None = None
                records = None
                try:
                    with progress_mod.scope(site=run.site, stage="scrape"):
                        _announce(run)
                        records = run.records(config)
                        for record in records:
                            if run.cancelled.is_set():
                                break
                            inbox.put((run, "record", record))
                except BaseException as exc:  # noqa: BLE001 - handed to the consuming thread
                    failure = exc
                finally:
                    if records is not None:
                        records.close()
                    inbox.put((run, "done", failure))

        threads = [threading.Thread(target=_work, name=f"scrape-{i}", daemon=True)
                   for i in range(min(pool_size, len(pooled)))]
        try:
            for thread in threads:
                thread.start()
            # Only this thread writes: records and finished sites arrive through `inbox`.
            remaining = len(pooled)
            while remaining:
                run, kind, payload = inbox.get()
                if kind == "record":
                    if run.cancelled.is_set():
                        continue
                    try:
                        run.accept(payload)
                    except Exception as exc:
                        run.failure = exc
                        run.cancelled.set()
                else:
                    remaining -= 1
                    _finish_run(run, payload)
        finally:
            # An interrupt (or any error) stops the producers and keeps what was written.
            for run in pooled:
                run.cancelled.set()
            store.save()

    site_results: list = [results[i] for i in range(n_sites)]
    written = [str(p) for p in candidates_paths]

    # Optional liveness verification pass
    liveness_result = None
    if config.get("verify_liveness", False):
        import door.core.liveness as liveness
        before = len(candidates_paths)
        # verify_liveness reports one event per posting itself.
        candidates_paths = liveness.verify_liveness(candidates_paths, config)
        liveness_result = {"before": before, "after": len(candidates_paths)}

    candidates_dir = workspace.day_dir(jobs_dir, run_date)
    passed = _scrape_passes(candidates_dir, config, profile_dir) if passes else {}
    employers = (sum(len(config.get(SITES[x].config_key) or []) for x in resolved_sites if SITES[x].config_key)
                 if collecting else None)

    return {
        "run_date": run_date,
        "mode": mode,
        "employers": employers,
        "written": written,
        "sites": site_results,
        "liveness": liveness_result,
        "prefilter": passed.get("prefilter"),
        "dedup": passed.get("dedup"),
        "condense": passed.get("condense"),
        "language": passed.get("language"),
        "prescreen": passed.get("prescreen"),
        "candidates_dir": str(candidates_dir),
        "surviving_paths": passed.get("surviving_paths", []),
    }


def _cutoff(site: str, collecting: bool, state: dict, max_age_days: int | None, now):
    """The oldest ``posted_at`` kept for *site*. A board: `freshness.site_cutoff` (watermark, at
    most `max_age_days`). An employer's feed: none, a posting is new when the history has not
    seen it."""
    return None if collecting else freshness.site_cutoff(site, state, max_age_days, now)


def _followed_for(profile_dir: Path, companies: list[str] | None) -> list[companies_store.Company]:
    """The followed employers with a feed; with *companies*, only those.

    Raises:
        ValueError: a name is not a followed employer.
    """
    items = companies_store.load(profile_dir)
    if not companies:
        return [c for c in items if c.status == "followed" and c.feed]
    out = []
    for name in companies:
        company = companies_store.find(items, name)
        if company is not None and company.status == "dormant":
            raise ValueError(f"{name!r} is dormant (no relevant job lately); `./door companies add {name}` follows it again")
        if company is None or company.status != "followed" or company.feed is None:
            raise ValueError(f"{name!r} is not a followed employer; `./door companies` lists them")
        out.append(company)
    return out


def _feed_config_for(profile_dir: Path, companies: list[str] | None) -> dict[str, list[str]]:
    """The followed employers' feed ids under the config keys the scrapers read; with *companies*,
    only those employers'.

    Raises:
        ValueError: a name is not a followed employer.
    """
    if not companies:
        return common._feed_config(profile_dir)
    out: dict[str, list[str]] = {}
    for company in _followed_for(profile_dir, companies):
        out.setdefault(sites.FEED_SITES[company.feed.platform], []).append(company.feed.id)
    return out



def _earlier_postings(candidates_dir: Path, max_age_days: int) -> list[Path]:
    """The postings of the days before *candidates_dir*'s (``jobs/postings/<YYYY-MM-DD>/``), at most
    *max_age_days* back: what dedup compares a new posting with, so an ad seen before under
    another source is not scored twice."""
    from datetime import date, timedelta

    try:
        day = date.fromisoformat(candidates_dir.name)
    except ValueError:
        return []
    oldest = (day - timedelta(days=max_age_days)).isoformat()
    days = [d for d in candidates_dir.parent.iterdir()
            if d.is_dir() and workspace.DAY_RE.fullmatch(d.name) and oldest <= d.name < candidates_dir.name]
    return sorted(p for d in days for p in d.glob("*/*.json"))


def _scrape_passes(candidates_dir: Path, config: dict, profile_dir: Path) -> dict:
    """The passes over `candidates_dir`: pre-filter, language, cross-site dedup, condense, prescreen.

    Language runs before dedup, so a copy the language pass drops (a board copy carrying a
    scraped cookie banner, say) can never be kept as the original of a duplicate group.

    Offline except the title translation. A posting already decided (scored, which includes the
    ones liveness found expired) is left alone, so running it again is harmless.

    Returns:
        ``{"prefilter", "dedup", "language", "condense", "prescreen", "surviving_paths"}`` as in
        `_scrape_core`'s result.
    """
    prefilter_result = None
    dedup_result = None
    language_result = None
    surviving: list = []

    if candidates_dir.exists():
        try:
            from door.matching.prefilter import prefilter
            progress_mod.report("pre-filter", stage="prefilter")
            surviving = prefilter(candidates_dir, config)
            prefilter_result = {"available": True, "survived": len(surviving)}
        except ImportError:
            prefilter_result = {"available": False}

        if surviving:
            # Tag each posting's language, drop the ones outside the profile's
            # `languages`, and translate the kept non-English titles so prescreen can
            # compare them with role_targets. One batched `claude -p` call per 50
            # titles; a failure only leaves `title_en` unset.
            from door.matching import language

            progress_mod.report("language", stage="language")
            surviving, language_result = language.filter_languages(surviving, config)

        # Cross-site dedup over what the language pass kept
        try:
            from door.matching.dedup import dedup as _dedup
            progress_mod.report("dedup", stage="dedup")
            aliases = [[c.name, *c.aliases] for c in companies_store.load(profile_dir) if c.aliases]
            earlier = _earlier_postings(candidates_dir, config.get("max_age_days") or common._DEFAULT_MAX_AGE_DAYS)
            dedup_surviving = _dedup(surviving, config, aliases=aliases, earlier=earlier)
            collapsed = len(surviving) - len(dedup_surviving)
            dedup_result = {"available": True, "collapsed": collapsed, "remaining": len(dedup_surviving)}
            surviving = dedup_surviving
        except ImportError:
            dedup_result = {"available": False}

    # Pre-match passes (issue #143): condense each posting's description to the
    # parts that matter for scoring and rank the survivors offline so only the
    # plausible ones are sent to the matcher.
    condense_result = None
    prescreen_result = None
    profile_terms: set = set()

    if surviving:
        try:
            from door.matching.condense import condense_postings, extract_skill_terms

            progress_mod.report("condense", stage="condense")

            cv_path = common._cv_path(config, profile_dir)
            if not cv_path.exists():
                cv_path = profile_dir / "cv.md"
            cv_md = cv_path.read_text() if cv_path.exists() else ""

            profile_terms = extract_skill_terms(cv_md, config)
            stats = condense_postings(surviving, profile_terms, config)
            ratio_pct = (
                round(stats["avg_ratio"] * 100) if stats.get("avg_ratio") is not None else None
            )
            condense_result = {
                "available": True,
                "count": stats["count"],
                "ratio_pct": ratio_pct,
            }
        except ImportError:
            condense_result = {"available": False}

        try:
            from door.matching.prescreen import prescreen as _prescreen

            progress_mod.report("prescreen", stage="prescreen")

            before = len(surviving)
            surviving = _prescreen(surviving, config, profile_terms)
            prescreen_result = {
                "available": True,
                "scored": before,
                "kept": len(surviving),
            }
        except ImportError:
            prescreen_result = {"available": False}

    return {"prefilter": prefilter_result, "dedup": dedup_result, "language": language_result,
            "condense": condense_result, "prescreen": prescreen_result,
            "surviving_paths": [str(p) for p in surviving]}


def _held_back(site: str, scrape_state: dict, now: "datetime") -> "dict | None":
    """The result of a site The other door sends no request to at all, or None: its terms reserve the
    content against scraping (issue #226), or it refused door last time and rests until its
    cooldown ends. `search` uses it too, to list only the boards it reads."""
    if SITES[site].verdict == "reserved":
        return {"site": site, "outcome": "reserved", "terms_url": SITES[site].terms_url}
    until = freshness.resting_until(site, SITES[site].cooldown_hours, scrape_state, now)
    if until is not None:
        return {"site": site, "outcome": "resting", "until": until.isoformat()}
    return None


def _site_done_message(entry: dict) -> str:
    """The one-line outcome of a site, shown live and sent with its closing event."""
    site = entry["site"]
    outcome = entry["outcome"]
    if outcome == "ok":
        message = f"{site}: {entry['count']} posting(s)"
        if entry.get("stale"):
            message += f", {entry['stale']} older than {common._local_time(entry['since'])} skipped"
        return message
    if outcome == "failed":
        errors = entry.get("errors", [])
        message = f"{site}: 0 posting(s), {_format_site_failure_detail(errors)}"
        return f"{message} — {errors[-1]}" if errors else message
    if outcome == "empty":
        return f"{site}: {entry['warning']}"
    if outcome == "not_implemented":
        return f"{site}: scraper not yet implemented, skipping."
    return f"{site}: error — {entry.get('error', '')}"


def _format_site_failure_detail(errors: list[str]) -> str:
    """Summarize a failed site's captured errors for the scrape summary line.

    If every message shares one clearly-extracted 3-digit HTTP-status-like
    code, render `"<code> xN"` (e.g. `"404 x8"`); otherwise fall back to a
    plain error count (e.g. `"3 errors"`). Deliberately shallow — this is a
    display aid, not general-purpose exception parsing (issue #132).
    """
    if not errors:
        return "0 errors"
    codes = [m.group(1) for msg in errors if (m := re.search(r"\b([1-5]\d{2})\b", msg))]
    if len(codes) == len(errors) and len(set(codes)) == 1:
        return f"{codes[0]} x{len(errors)}"
    return "1 error" if len(errors) == 1 else f"{len(errors)} errors"


def _empty_site_warning(site, config: dict) -> str:
    """Why a site that returned nothing at all is worth a look (`site` is a `Site`)."""
    return (
        "returned no results at all — the site may have changed. "
        "`doctor --probe` checks the site and `setup` can fix its scraper."
    )


def _scrape_result_lines(result: dict, *, shown=(), tally: bool = True) -> list[tuple[str, str]]:
    """`_echo_scrape_result`'s lines as ``[(mark, text), ...]`` (mark: ok/warn/fail/info).

    ``shown`` names the sites a live progress line already reported; they get no line.
    ``tally``: also a ``Sites: n ok, n failed: …, n empty: …`` line when any site
    failed or came back empty (`find` leaves it out: its Summary grid lists failures).
    """
    lines: list[tuple[str, str]] = []
    for entry in result["sites"]:
        site = entry["site"]
        if site in shown:
            continue
        outcome = entry["outcome"]
        if outcome == "ok":
            lines.append(("ok", f"{site}: {entry['count']} posting(s) written to {common._display_path(entry['dir'])}"))
            if entry.get("stale"):
                lines.append((
                    "info",
                    f"{site}: {entry['stale']} older than {common._local_time(entry['since'])} skipped",
                ))
        elif outcome == "not_implemented":
            lines.append(("info", f"{site}: scraper not yet implemented, skipping."))
        elif outcome == "reserved":
            lines.append(("info", f"{site}: skipped — its terms reserve it against scraping ({entry['terms_url']})."))
        elif outcome == "resting":
            lines.append((
                "info",
                f"{site}: skipped — resting after it pushed back; next try after {common._local_time(entry['until'])}.",
            ))
        elif outcome == "not_configured":
            lines.append((
                "info",
                f"{site}: skipped — no employers followed on it (`./door companies add <name or link>`).",
            ))
        elif outcome == "failed":
            errors = entry.get("errors", [])
            last = errors[-1] if errors else "no error message was recorded"
            lines.append(("fail", f"{site}: 0 posting(s), {_format_site_failure_detail(errors)} — {last}"))
        elif outcome == "empty":
            lines.append(("warn", f"{site}: {entry['warning']}"))
        else:
            lines.append(("fail", f"{site}: error — {entry['error']}"))

    failed_sites = [e for e in result["sites"] if e["outcome"] == "failed"]
    empty_sites = [e["site"] for e in result["sites"] if e["outcome"] == "empty"]
    if tally and (failed_sites or empty_sites):
        n_ok = sum(1 for e in result["sites"] if e["outcome"] == "ok")
        parts = [f"{n_ok} ok"]
        if failed_sites:
            detail = ", ".join(
                f"{e['site']} ({_format_site_failure_detail(e.get('errors', []))})" for e in failed_sites
            )
            parts.append(f"{len(failed_sites)} failed: {detail}")
        if empty_sites:
            parts.append(f"{len(empty_sites)} empty: {', '.join(empty_sites)}")
        lines.append(("fail" if failed_sites else "warn", "Sites: " + ", ".join(parts)))

    if result["liveness"] is not None:
        lines.append((
            "ok",
            f"Liveness check complete: {result['liveness']['after']} posting(s) verified live/indeterminate "
            f"(of {result['liveness']['before']}).",
        ))

    if result["prefilter"] is not None:
        if result["prefilter"]["available"]:
            lines.append(("ok", f"Pre-filter complete: {result['prefilter']['survived']} candidate(s) passed."))
        else:
            lines.append(("info", "Pre-filter not yet implemented, skipping."))
        if result["dedup"] is not None and result["dedup"]["available"]:
            lines.append((
                "ok",
                f"Dedup complete: {result['dedup']['collapsed']} duplicate(s) collapsed, "
                f"{result['dedup']['remaining']} candidate(s) remaining.",
            ))

    if result["condense"] is not None:
        if result["condense"]["available"]:
            ratio_pct = result["condense"]["ratio_pct"]
            reduced_text = f", size reduced {100 - ratio_pct}%" if ratio_pct is not None else ""
            lines.append(("ok", f"Condense complete: {result['condense']['count']} description(s) condensed{reduced_text}."))
        else:
            lines.append(("info", "Condense not yet implemented, skipping."))

    if result.get("language") is not None:
        lang = result["language"]
        counts = ", ".join(f"{code} {n}" for code, n in sorted(lang["languages"].items()))
        line = f"Languages: {counts}"
        if lang["dropped"]:
            line += f"; {lang['dropped']} dropped (no description, or not in languages)"
        if lang["translated"]:
            line += f"; {lang['translated']} title(s) translated"
        if lang["failed_batches"]:
            line += (
                f"; title translation failed for {lang['failed_batches']} batch(es) "
                "— prescreen used the original titles"
            )
        lines.append(("warn" if lang["failed_batches"] else "ok", line + "."))

    if result["prescreen"] is not None:
        if result["prescreen"]["available"]:
            lines.append((
                "ok",
                f"Prescreen complete: {result['prescreen']['kept']} of "
                f"{result['prescreen']['scored']} candidate(s) sent forward for scoring.",
            ))
        else:
            lines.append(("info", "Prescreen not yet implemented, skipping."))
    return lines


def _echo_scrape_result(result: dict, *, shown=(), tally: bool = True, console=None) -> None:
    """Render a `_scrape_core` result dict: `find`'s scrape-stage detail, one
    ``✓``/``⚠``/``✗``/``·`` line each (`_common._mark_line`).

    ``shown`` names the sites a live progress line already reported (see
    `_progress.LiveLine.finished_sites`); they get no line here. Sites skipped
    without scraping (not configured, reserved), failures, empty sites and
    every pass result (liveness, pre-filter, dedup, condense, languages,
    prescreen) are always printed. Messages are plain text, never rich markup.
    """
    from rich.text import Text

    console = console or common._console()
    for kind, text in _scrape_result_lines(result, shown=shown, tally=tally):
        common._mark_line(console, kind, Text(text, style="dim" if kind == "info" else ""))
