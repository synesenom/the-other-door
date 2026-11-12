"""Step 2, `discover`: which employers hire for the keywords, from the discovery sources.

A discovery source is not a job source; it only tells which employers hire for the profile's
keywords. Today there is one, LinkedIn (`door.scrapers.discovery.linkedin`); a source is a module registered
in `door.core.discovery_sources` that follows the contract documented there (``NAME``,
``COUNTRIES``, ``CONFIG_KEY``, ``run`` and the optional hooks ``extras`` and ``skip_employer``), so
another one plugs in without a change to this file. This step runs every source the profile enables
for its country, one after the other, and puts each employer in the candidates queue
(`jobs/candidates.json`, the source named in ``sources``) for `follow`.

Each source has its own state, `jobs/discovery/<source>.json` (`door.core.discovery_state`: pace,
rest after a refusal, keyword rotation, history), its own request budget and pause, and its own
progress and error bookkeeping; one source resting, off or crashing never blocks another. The block
keeps its flat fields (sums over the sources that ran; with one source, exactly its values) and gains
``sources``, the breakdown by source.

For LinkedIn (`door.scrapers.discovery.linkedin`: one quoted search per keyword, each paged newest first
through the last 7 days; paced and capped):

* A new employer is queued with only its LinkedIn link: `follow` tries it by name first (the name
  probe, then the model) and records it when that finds a feed. No LinkedIn job page is fetched
  for it.
* An employer `follow` could not resolve by name (it is *parked*: ``name_tried``, no apply link)
  gets its job page read, oldest first, with the request budget the search left (the source's
  ``extras`` hook lists them). A page that shows an offsite apply link queues that link; one that
  shows none (Easy Apply) is remembered 90 days in the source's state and not queued (its
  ``skip_employer`` hook): there is nothing to follow.

**Pace.** A run makes at most ``pace.budget`` requests per source (search pages and job pages together),
pausing 2 to 4 s (times ``pace.factor``) between two; a refusal halves the next budget and
doubles the next pause, three clean runs step back (`door.core.discovery_state`, which also logs
every run's observation in ``history``). A source rests a day after it refuses (a 429, a
login wall), and is skipped when its ``<source>_discovery`` key is off (``linkedin_discovery``). A
crash is reported in the block, never raised.

**In the background.** A full ``find`` starts discover first (`begin`) and
lets it work on a worker thread while search, follow and collect run. The thread only talks to
the sources and keeps their results in memory; every `jobs/` ledger is written by the caller's thread,
in `Discovery.finish`, which reloads the queue and the employer list as the other steps left them.
`find` calls `finish` once the thread is done (or waits for it after collect) and runs a short
"late" follow and collect for the employers it queued. When the thread's requests end it reports
how (``li_end``, the generic end-of-requests stage, whatever the source), and the step's line shows
it done; `finish` later gives it its summary.
``find discover`` alone works in the foreground (`_discover_core`, same pace).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from door import pipeline, scrapers
from door.commands import _common as common
from door.core import candidates, discovery_sources, discovery_state, progress, workspace
from door.core import companies as store
from door.matching import title_fit

_ROTATE_PER_RUN = 1000  # keywords a run in rotate mode lines up: all of them, the budget decides how far it gets
_SOURCE_FIELDS = ("employers", "queued", "requests", "budget", "pause", "outcome", "stopped", "skipped", "error")


def _pace_text(pause) -> str:
    return f"{pause[0]:g}-{pause[1]:g} s pause"


def _summary(block: dict) -> str:
    parts = [f"{block['employers']} employers", f"{block['queued']} queued"]
    if block["requests"]:
        parts.append(f"{block['pages']} pages + {block['details']} job pages ({block['requests']}/{block['budget']} "
                     f"requests, {_pace_text(block['pause'])}, {block['mode']})")
    else:
        parts.append(f"no request (budget {block['budget']}, {_pace_text(block['pause'])}, {block['mode']})")
    if block["stopped"]:
        parts.append(f"stopped: {block['stopped']}")
    ran = [(n, s) for n, s in block["sources"].items() if not s["skipped"]]
    if len(ran) > 1:
        parts.append("; ".join(f"{n}: {s['employers']} employers, {s['queued']} queued" for n, s in ran))
    return ", ".join(parts)


def _ended_text(result: dict | None, crash: BaseException | None) -> str:
    """How one source's network part ended, for the step's line while its result waits for `finish`:
    ``85/150 requests, budget spent; queuing at the next step``."""
    if crash is not None:
        return f"failed: {type(crash).__name__}: {crash}"
    if result["stopped"]:
        how = f"stopped: {result['stopped']}"
    else:
        how = "budget spent" if result["outcome"] == "budget" else "search complete"
    return f"{result['requests']}/{result['budget']} requests, {how}; queuing at the next step"


def _source_block(name: str) -> dict:
    return {"source": name, "skipped": None, "employers": 0, "details": 0, "pages": 0, "requests": 0, "queued": 0,
            "easy_apply": 0, "budget": 0, "pause": [0, 0], "mode": "", "mode_switched": False,
            "search_complete": False, "outcome": None, "stopped": None, "error": None}


class Discovery:
    """One discovery run, split in two: `_run_network` talks to the sources (on a worker thread or the
    caller's) and keeps their results in memory; `finish` applies them to the ledgers on the caller's
    thread. Make one with `begin`."""

    def __init__(self, jobs_dir: Path, profile_dir: Path) -> None:
        self.jobs_dir, self.profile_dir = jobs_dir, profile_dir
        self.config = common._load_config(profile_dir)
        self.block = {"step": "discover", "skipped": None, "employers": 0, "details": 0, "pages": 0, "requests": 0,
                      "queued": 0, "easy_apply": 0, "budget": 0, "pause": [0, 0], "mode": "", "mode_switched": False,
                      "search_complete": False, "outcome": None, "stopped": None, "error": None, "elapsed_s": 0.0,
                      "summary": "", "sources": {}}
        self.started = time.monotonic()
        self.now = datetime.now(timezone.utc)
        self.stop = threading.Event()
        self.sources: list[SimpleNamespace] = []
        self._thread: threading.Thread | None = None
        self._applied = False
        self.skipped = self._prepare()

    # -- main thread: read what the network part needs --------------------------------------------
    def _prepare(self) -> str | None:
        config, now = self.config, self.now
        self.keywords = title_fit.keywords(config)
        queue = candidates.load(self.jobs_dir)
        items = common._company_items(self.profile_dir)
        max_age = config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS)
        settled = {c.name for c in items if store.is_settled(items, c.name, now)}
        queued_with_link = {e["name"] for e in queue.values() if not candidates.needs_apply_link(e)}
        for name, module, reason in discovery_sources.selected(config):
            src = SimpleNamespace(name=name, module=module, skipped=reason, result=None, crash=None, ran=False,
                                  block=_source_block(name), state=None, kwargs={})
            self.sources.append(src)
            self.block["sources"][name] = src.block
            if reason is not None and reason.startswith("not for "):
                src.block["skipped"] = reason
                continue
            src.state = discovery_state.load(self.jobs_dir, name)
            pace = discovery_state.pace(src.state)
            mode = discovery_state.search_mode(src.state)
            src.block.update(budget=pace["budget"], pause=list(pace["pause"]), mode=mode)
            if reason is None and not self.keywords:
                reason = "no search keywords or role targets in the profile"
            elif reason is None:
                resting = discovery_state.resting_until(src.state, now, name)
                if resting is not None:
                    label = getattr(module, "LABEL", name)
                    reason = f"{label} resting until {resting.astimezone().strftime('%H:%M')}"
            src.skipped = src.block["skipped"] = reason
            if reason:
                continue
            seen = discovery_state.known(src.state, now)
            rotation = discovery_state.rotation(src.state, self.keywords, _ROTATE_PER_RUN)
            src.kwargs = {
                "since": discovery_state.since(src.state, max_age, now),
                "keyword_since": {k.lower(): discovery_state.keyword_since(src.state, k, max_age, now)
                                  for k in rotation},
                "known_companies": frozenset(settled | seen | queued_with_link),
                "budget": pace["budget"], "pause": pace["pause"], "mode": mode, "rotation": rotation,
                "stop": self.stop,
            }
            if hasattr(module, "extras"):
                src.kwargs.update(module.extras(queue))
        return self._aggregate_skip()

    def _aggregate_skip(self) -> str | None:
        """The step's skip reason: set only when no source runs. Fills the flat fields from the first source."""
        first = self.sources[0] if self.sources else None
        if first is not None:
            self._flat_from(first.block)
        if any(not s.skipped for s in self.sources):
            self.block["budget"] = sum(s.block["budget"] for s in self.sources if not s.skipped)
            return None
        reasons = [s.skipped for s in self.sources if s.skipped and not s.skipped.startswith("not for ")]
        reasons = reasons or [s.skipped for s in self.sources if s.skipped] or ["no discovery source"]
        reason = "; ".join(reasons)
        self.block["skipped"] = reason
        self.block["summary"] = f"skipped: {reason}"
        return reason

    def _flat_from(self, src_block: dict) -> None:
        self.block.update(budget=src_block["budget"], pause=list(src_block["pause"]), mode=src_block["mode"])

    # -- the network part -------------------------------------------------------------------------
    def _run_network(self) -> None:
        """Talk to the sources, one after the other; never write `jobs/`. Runs on a worker thread or the caller's."""
        texts, failed = [], False
        running = [s for s in self.sources if not s.skipped]
        for src in running:
            if self.stop.is_set() and src is not running[0]:
                continue  # cancelled before this one began
            src.ran = True
            pipeline.item("discover", src.name, "start")
            try:
                src.result = src.module.run(self.config, **src.kwargs)
            except BaseException as exc:  # noqa: BLE001 - reported by `finish`, never lost with the thread
                src.crash = exc
            refused = src.result is not None and src.result.get("outcome") in ("refused", "error")
            pipeline.item("discover", src.name, "failed" if src.crash is not None or refused else "done")
            failed = failed or src.crash is not None
            texts.append((src.name, _ended_text(src.result, src.crash)))
        done = sum(s.result["requests"] for s in running if s.result is not None) if running else None
        total = sum(s.result["budget"] for s in running if s.result is not None) if running else None
        if len(texts) == 1:
            message, site = texts[0][1], texts[0][0]
        else:
            message, site = "; ".join(f"{n}: {t}" for n, t in texts), "discover"
        if all(s.result is None for s in running):
            done = total = None
        progress.report(message, done, total, site=site, stage="li_end", outcome="failed" if failed else "done")

    def start(self) -> None:
        """Run the network part on a worker thread."""
        self._thread = threading.Thread(target=self._run_network, name="discover", daemon=True)
        self._thread.start()

    def run(self) -> None:
        """Run the network part on this thread."""
        self._run_network()

    def ready(self) -> bool:
        """Whether the network part is over (always true for a skipped step)."""
        return self._thread is None or not self._thread.is_alive()

    def wait_ready(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.ready()

    def cancel(self) -> None:
        """Ask the network part to end at its next request."""
        self.stop.set()

    # -- the caller's thread: write the ledgers ---------------------------------------------------
    def finish(self) -> dict:
        """Wait for the network part, apply its results to the queue and the states, report the
        step done; returns the block. Idempotent. Never raises for a source's problem."""
        if self._applied:
            return self.block
        self._applied = True
        if self.skipped:
            pipeline.skipped("discover", self.skipped)
            return self.block
        self.wait_ready()
        block = self.block
        for src in self.sources:
            if src.skipped or not src.ran:
                continue
            try:
                if src.crash is not None:
                    raise src.crash
                self._apply(src)
            except Exception as exc:  # noqa: BLE001 - a discovery failure never fails the run
                src.block["error"] = f"{type(exc).__name__}: {exc}"
        for src in self.sources:
            scrapers.drain_errors(src.name)  # discovery reports through its result, not a scrape outcome
            scrapers.drain_pushback(src.name)
        self._aggregate()
        block["elapsed_s"] = time.monotonic() - self.started
        block["summary"] = _summary(block)
        pipeline.finished("discover", block["summary"], block["error"])
        return block

    def _aggregate(self) -> None:
        block = self.block
        ran = [s.block for s in self.sources if not s.skipped]
        for key in ("employers", "details", "pages", "requests", "queued", "easy_apply", "budget"):
            block[key] = sum(b[key] for b in ran)
        if ran:
            block.update(pause=list(ran[0]["pause"]), mode=ran[0]["mode"])
        block["mode_switched"] = any(b["mode_switched"] for b in ran)
        block["search_complete"] = bool(ran) and all(b["search_complete"] for b in ran)
        outcomes = [b["outcome"] for b in ran if b["outcome"] is not None]
        block["outcome"] = (outcomes[0] if len(set(outcomes)) == 1 else
                            next((o for o in outcomes if o != "ok"), None)) if outcomes else None
        block["stopped"] = next((b["stopped"] for b in ran if b["stopped"]), None)
        errors = [b["error"] for b in ran if b["error"]]
        block["error"] = "; ".join(errors) if errors else None

    def _apply(self, src: SimpleNamespace) -> None:
        result, state, name, module = src.result, src.state, src.name, src.module
        block, now = src.block, datetime.now(timezone.utc)
        jobs_dir, profile_dir = self.jobs_dir, self.profile_dir
        block.update(employers=len(result["employers"]), details=result["details"], pages=result["pages"],
                     requests=result["requests"], stopped=result["stopped"], mode=result["mode"],
                     mode_switched=result["mode_switched"], search_complete=result["search_complete"],
                     outcome=result["outcome"], budget=result["budget"], pause=list(result["pause"]))
        # The other steps wrote the queue and the employer list meanwhile: start from what is there.
        queue = candidates.load(jobs_dir)
        items = common._company_items(profile_dir)
        seen = discovery_state.known(state, now)
        before = set(queue)
        for emp in result["employers"]:
            emp_name, key = emp["company"], store.name_key(emp["company"])
            if store.is_settled(items, emp_name, now) or emp_name.lower() in seen:
                queue.pop(key, None)
                continue
            why = module.skip_employer(emp, state, now) if hasattr(module, "skip_employer") else None
            if why:
                queue.pop(key, None)  # nothing to follow (LinkedIn's Easy Apply)
                discovery_state.record(state, emp_name, why, now)
                if why == "easy_apply":
                    block["easy_apply"] += 1
                continue
            first = common._parse_iso(emp.get("first_seen")) or now
            candidates.add(queue, emp_name, links=emp["links"], titles=emp["titles"], source=name, now=now,
                           job_ids=emp["job_ids"])
            queue[key]["first_seen"] = min(queue[key]["first_seen"], first.isoformat())
        block["queued"] = len(set(queue) - before)
        candidates.save(jobs_dir, queue)

        if result["mode_switched"]:
            state["mode"] = result["mode"]
        if result["mode"] == "rotate" and result["searched"]:
            for keyword in result["searched"]:
                discovery_state.mark_searched(state, keyword, now)
            discovery_state.advance_rotation(state, self.keywords, len(result["searched"]))
        if result["stopped"] is None:
            discovery_state.finish(state, now)
        elif result["pushback"]:
            discovery_state.refused(state, now)
        discovery_state.record_run(
            state, now, mode=result["mode"], requests=result["requests"], pages=result["pages"],
            job_pages=result["details"], outcome=result["outcome"], seconds=result["seconds"],
            first_429=result["first_429"])
        discovery_state.save(jobs_dir, name, state)


def begin(*, jobs_dir: Path | None = None, profile_dir: Path | None = None, background: bool = True) -> Discovery:
    """Prepare a discovery run (on this thread: the files it reads) and, unless it is skipped, start
    its network part on a worker thread (*background*) — report the step started. The caller must
    hold the ledger lock and call `Discovery.finish` (or `cancel` then `finish`) on its own thread.

    Raises:
        ConfigError / FileNotFoundError: the profile config is missing or invalid.
    """
    jobs_dir = workspace.JOBS_DIR if jobs_dir is None else jobs_dir
    profile_dir = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    discovery = Discovery(jobs_dir, profile_dir)
    if discovery.skipped is None:
        pipeline.started("discover", total=discovery.block["budget"])
        pipeline.items("discover", [(s.name, getattr(s.module, "LABEL", s.name)) for s in discovery.sources if not s.skipped])
        if background:
            discovery.start()
    return discovery


@common._locked("discover")
def _discover_core(
    *, jobs_dir: Path | None = None, profile_dir: Path | None = None, progress=None,
) -> dict:
    """Ask the discovery sources (LinkedIn) which employers hire for the keywords and queue them, in the
    foreground (a full `find` uses `begin` instead). Never prints, never raises for a source's problem.

    Returns:
        ``{"step": "discover", "skipped": reason | None, "employers", "details" (job pages read),
        "pages" (search pages), "requests", "budget", "pause": [low, high] seconds, "mode" (``rotate``
        or ``combined``), "mode_switched", "search_complete", "outcome" (``ok``, ``budget``, ``refused``,
        ``error``, ``cancelled``), "queued", "easy_apply", "stopped": reason | None, "error": message | None,
        "elapsed_s", "summary"}`` — ``skipped`` says why nothing ran (every source off, no
        keywords, or resting after a refusal); the fields are sums over the sources that ran, and
        ``sources`` is ``{name: {"employers", "queued", "requests", "budget", "pause", "outcome",
        "stopped", "skipped", "error", ...}}`` for each registered source; ``queued`` is how many employers were new to the queue;
        ``stopped`` is why a run ended early.

    Raises:
        ConfigError / FileNotFoundError: the profile config is missing or invalid.
    """
    discovery = begin(jobs_dir=jobs_dir, profile_dir=profile_dir, background=False)
    if discovery.skipped is None:
        discovery.run()
    return discovery.finish()
