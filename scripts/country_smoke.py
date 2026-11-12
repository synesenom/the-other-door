"""Live smoke run of a whole country: the country-validator's sandbox profiles as a repeatable script.

Per fake profile (the example CV, the capital as `location`, broad keywords) it runs `search`
(every board serving the country), `discover` (a small LinkedIn request budget), `follow` (a
judged dry run, then a real one in the sandbox), `collect` (a few followed employers) and `match`
(a few postings scored, or stubbed), judges each step's run-record block into PASS / FAIL /
SITE-SIDE / SKIP lines and writes `thoughts/country/<cc>/smoke-<date>.md`. Exit code 1 only when a
line FAILs. Everything runs in throwaway sandboxes (`scripts/sandbox.py`: never your profile, jobs
or Google Drive); the sites are real, so it is opt-in and not in CI. Run it before a release,
after a board breaks, or after a change to locality, language or follow.

A `resting` board, a refused or resting LinkedIn is SITE-SIDE, not a fail. Every run starts from fresh
sandboxes: only the previous ones' 24 h rests (`pushback_at`) are carried over, never the
watermarks, so a repeat run reads each board whole; the day's report is replaced. Search and discover run once per country; the local-language profile gets a copy
of the English one's `jobs/` before match.

Usage:  poetry run python scripts/country_smoke.py <cc> [--langs en|local|both] [--stub-scoring]
                                                   [--collect N] [--budget N] [--dir DIR] [--profession NAME]
   e.g. poetry run python scripts/country_smoke.py hu --langs both
        poetry run python scripts/country_smoke.py dk --langs en --stub-scoring --collect 2
        poetry run python scripts/country_smoke.py dk --profession nurse   # one of tests/professions.py's six profiles
"""

import argparse
import importlib.util
import json
import shutil
import sys
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from door.commands import _common as common  # noqa: E402
from door.commands import find as find_cmd  # noqa: E402
from door.core import candidates, companies, workspace  # noqa: E402
from door.matching import scorer  # noqa: E402

_spec = importlib.util.spec_from_file_location("sandbox", Path(__file__).resolve().parent / "sandbox.py")
sandbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sandbox)

PASS, FAIL, SITE_SIDE, SKIP = "PASS", "FAIL", "SITE-SIDE", "SKIP"

# One row per (country, ad languages); the names are those of tests/pipeline/test_pipeline_countries_end_to_end.py's
# COUNTRIES (a test pins them). A new country's rows go here too (see `/dev-add-country`).
PROFILES = {
    "dk-en": {"cc": "dk", "location": "Copenhagen, Denmark", "languages": ["English"], "local_language": "da",
              "keywords": ["accountant", "nurse", "sales manager", "software engineer", "revisor", "sygeplejerske"],
              "floor": 0.5},
    "hu-en": {"cc": "hu", "location": "Budapest, Hungary", "languages": ["English"], "local_language": "hu",
              "keywords": ["accountant", "nurse", "sales manager", "software engineer", "könyvelő", "ápoló"],
              "floor": 0.5},
    "hu-en-hu": {"cc": "hu", "location": "Budapest, Hungary", "languages": ["English", "Hungarian"],
                 "local_language": "hu",
                 "keywords": ["accountant", "nurse", "sales manager", "software engineer", "könyvelő", "ápoló"],
                 "floor": 0.5},
    "fr-en": {"cc": "fr", "location": "Paris, France", "languages": ["English"], "local_language": "fr",
              "keywords": ["accountant", "nurse", "sales manager", "software engineer", "comptable", "infirmier"],
              "floor": 0.5},
    "fr-en-fr": {"cc": "fr", "location": "Paris, France", "languages": ["English", "French"],
                 "local_language": "fr",
                 "keywords": ["accountant", "nurse", "sales manager", "software engineer", "comptable", "infirmier"],
                 "floor": 0.5},
    "se-en": {"cc": "se", "location": "Stockholm, Sweden", "languages": ["English"], "local_language": "sv",
              "keywords": ["accountant", "nurse", "sales manager", "software engineer", "redovisningsekonom", "sjuksköterska"],
              "floor": 0.5},
    "se-en-sv": {"cc": "se", "location": "Stockholm, Sweden", "languages": ["English", "Swedish"],
                 "local_language": "sv",
                 "keywords": ["accountant", "nurse", "sales manager", "software engineer", "redovisningsekonom", "sjuksköterska"],
                 "floor": 0.5},
    "gb-en": {"cc": "gb", "location": "London, United Kingdom", "languages": ["English"], "local_language": None,
              "keywords": ["accountant", "nurse", "sales manager", "software engineer"],
              "floor": 0.5},
}
# One Danish row per profession (#427): the six profiles of tests/professions.py (a test pins the two together), run
# alone with `--profession`, never by the plain `dk` run.
PROFESSION_ROWS = {
    "dk-software_engineer": {"cc": "dk", "location": "Copenhagen, Denmark", "languages": ["English", "Danish"], "local_language": "da",
        "profession": "software_engineer", "floor": 0.5,
        "role_targets": ['Software Engineer', 'Backend Developer', 'Full Stack Engineer'],
        "keywords": ['software engineer', 'backend developer', 'full stack developer', 'python developer', 'softwareudvikler', 'backendudvikler', 'fullstack udvikler'],
        "topic_terms": ['software engineer', 'software developer', 'backend developer', 'full stack', 'fullstack', 'python developer', 'softwareudvikler', 'backendudvikler', 'udvikler']},
    "dk-researcher": {"cc": "dk", "location": "Copenhagen, Denmark", "languages": ["English", "Danish"], "local_language": "da",
        "profession": "researcher", "floor": 0.5,
        "role_targets": ['Postdoc in Physics', 'Assistant Professor of Physics', 'Research Scientist, Astrophysics'],
        "keywords": ['postdoc physics', 'assistant professor physics', 'astrophysics', 'biophysics', 'adjunkt fysik', 'postdoc fysik', 'lektor fysik', 'forsker fysik', 'astrofysik', 'kvantefysik'],
        "topic_terms": ['postdoc', 'postdoc physics', 'physics', 'astrophysics', 'biophysics', 'quantum', 'adjunkt', 'lektor', 'professor', 'fysik', 'astrofysik', 'biofysik', 'kvante', 'forsker', 'Niels Bohr Institute', 'Niels Bohr Institutet', 'Institut for Fysik og Astronomi', 'DTU Physics', 'DTU Fysik', 'Department of Physics and Astronomy']},
    "dk-accountant": {"cc": "dk", "location": "Copenhagen, Denmark", "languages": ["English", "Danish"], "local_language": "da",
        "profession": "accountant", "floor": 0.5,
        "role_targets": ['Accountant', 'Financial Accountant', 'Bookkeeper'],
        "keywords": ['accountant', 'financial accountant', 'bookkeeper', 'accounts payable', 'bogholder', 'regnskabsmedarbejder', 'regnskabsassistent', 'økonomimedarbejder', 'revisorassistent'],
        "topic_terms": ['accountant', 'accounting', 'bookkeeper', 'bookkeeping', 'accounts payable', 'accounts receivable', 'general ledger', '*bogholder', 'bogholderi', 'regnskab*', 'økonomimedarbejder', 'økonomiassistent', 'revisorassistent']},
    "dk-nurse": {"cc": "dk", "location": "Copenhagen, Denmark", "languages": ["English", "Danish"], "local_language": "da",
        "profession": "nurse", "floor": 0.5,
        "role_targets": ['Nurse', 'Intensive Care Nurse', 'Registered Nurse'],
        "keywords": ['nurse', 'registered nurse', 'intensive care nurse', 'sygeplejerske', 'intensivsygeplejerske', 'anæstesisygeplejerske', 'afdelingssygeplejerske', 'hjemmesygeplejerske'],
        "topic_terms": ['nurse', 'sygeplejerske', 'intensivsygeplejerske', 'anæstesisygeplejerske', 'afdelingssygeplejerske', 'hjemmesygeplejerske', 'sygepleje', 'intensive care', 'ward nurse']},
    "dk-shop_sales": {"cc": "dk", "location": "Copenhagen, Denmark", "languages": ["English", "Danish"], "local_language": "da",
        "profession": "shop_sales", "floor": 0.5,
        "role_targets": ['Shop Assistant', 'Sales Assistant', 'Retail Sales Associate'],
        "keywords": ['shop assistant', 'sales assistant', 'retail sales associate', 'store associate', 'butiksassistent', 'butiksmedarbejder', 'salgsassistent', 'ekspedient', 'kassemedarbejder'],
        "topic_terms": ['shop assistant', 'sales assistant', 'sales associate', 'store associate', 'butik*', 'salgsassistent', 'ekspedient', 'kassemedarbejder', 'kasseassistent']},
    "dk-electrician": {"cc": "dk", "location": "Copenhagen, Denmark", "languages": ["English", "Danish"], "local_language": "da",
        "profession": "electrician", "floor": 0.5,
        "role_targets": ['Electrician', 'Service Electrician', 'Journeyman Electrician'],
        "keywords": ['electrician', 'service electrician', 'elektriker', 'serviceelektriker', 'autoriseret elektriker', 'svend elektriker', 'elinstallatør'],
        "topic_terms": ['electrician', 'elektriker', 'serviceelektriker', 'installatør', 'autoriseret elektriker', 'elektrikersvend', 'svend elektriker', 'el-installatør']},
}
PROFILES.update(PROFESSION_ROWS)
_LANGUAGE_CODES = {"English": "en", "Danish": "da", "Hungarian": "hu", "Swedish": "sv", "French": "fr"}


@dataclass
class Line:
    step: str
    name: str
    status: str
    detail: str = ""


# --------------------------------------------------------------------------- #
# Judges: pure functions of the run-record blocks
# --------------------------------------------------------------------------- #

def judge_search(block: dict) -> list[Line]:
    lines = []
    for site in block.get("sites") or []:
        name, outcome, count = site.get("site", "?"), site.get("outcome"), site.get("count", 0)
        if outcome == "resting":
            lines.append(Line("search", name, SITE_SIDE, f"resting until {site.get('until')}"))
        elif outcome == "not_configured":
            lines.append(Line("search", name, SKIP, "not configured"))
        elif outcome in ("failed", "error", "empty"):
            why = "; ".join(site.get("errors") or []) or site.get("warning") or outcome
            lines.append(Line("search", name, FAIL, f"{outcome}: {why}"))
        elif outcome == "ok" and count > 0:
            lines.append(Line("search", name, PASS, f"{count} postings"))
        else:
            lines.append(Line("search", name, FAIL, f"{outcome}: returned nothing"))
    return lines


def _judge_source(name: str, block: dict) -> Line:
    if block.get("queued", 0) > 0:
        return Line("discover", name, PASS, f"{block['queued']} employers queued")
    skipped = block.get("skipped")
    if skipped:
        status = SITE_SIDE if "resting" in skipped else FAIL
        return Line("discover", name, status, f"skipped: {skipped}")
    if block.get("outcome") == "refused" or block.get("pushback"):
        return Line("discover", name, SITE_SIDE, f"{name} refused (pushback)")
    return Line("discover", name, FAIL, f"queued no employer (outcome {block.get('outcome')}, "
                                         f"error {block.get('error')})")


def judge_discover(block: dict | None) -> list[Line]:
    """One line per discovery source that serves the country (the block's flat fields are sums over them)."""
    if block is None:
        return [Line("discover", "linkedin", SKIP, "step did not run")]
    sources = block.get("sources")
    if not sources:
        return [_judge_source("linkedin", block)]
    lines = [_judge_source(n, b) for n, b in sources.items() if not str(b.get("skipped") or "").startswith("not for ")]
    return lines or [_judge_source("linkedin", block)]


def cap_queue(jobs_dir: Path, limit: int) -> int:
    """Keep at most *limit* queued employers (0 = all), taken in turn from each source so none crowds out the
    rest; returns how many were queued before. A country check follows a sample, not 300 employers."""
    queue = candidates.load(jobs_dir)
    before = len(queue)
    if limit <= 0 or before <= limit:
        return before
    groups: dict[str, list[str]] = {}
    for key, entry in queue.items():
        groups.setdefault((entry.get("sources") or [""])[0], []).append(key)
    keep: list[str] = []
    lists = list(groups.values())
    while len(keep) < limit and any(lists):
        for lst in lists:
            if lst and len(keep) < limit:
                keep.append(lst.pop(0))
    candidates.save(jobs_dir, {k: queue[k] for k in keep})
    return before


def copy_jobs(src_sandbox: Path, dst_sandbox: Path) -> None:
    """The first sandbox's jobs/ for the second one, without its run records (their `dir` names the first's paths)."""
    shutil.copytree(Path(src_sandbox) / "jobs", Path(dst_sandbox) / "jobs", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("runs"))


def judge_follow(block: dict) -> list[Line]:
    followed, unresolved = block.get("followed") or [], block.get("unresolved") or []
    unfollowable = block.get("unfollowable") or []
    detail = f"{len(followed)} followed, {len(unresolved)} unresolved, {len(unfollowable)} unfollowable"
    if unresolved:
        detail += "; unresolved: " + ", ".join(f"{u['company']} ({u.get('reason')})" for u in unresolved[:2])
    return [Line("follow", "dry run", PASS, detail)]


def local_share(search_block: dict | None, collect_block: dict | None) -> float | None:
    """Postings kept / (kept + left unread as non-local), over the boards and the collected feeds."""
    sites = (search_block or {}).get("sites") or []
    kept = sum(s.get("count", 0) for s in sites if s.get("outcome") == "ok") + (collect_block or {}).get("postings", 0)
    foreign = sum(s.get("non_local", 0) for s in sites) + (collect_block or {}).get("non_local", 0)
    return kept / (kept + foreign) if kept + foreign else None


def judge_collect(block: dict, followed: list[str], share: float | None, floor: float) -> list[Line]:
    if not followed:
        return [Line("collect", "feeds", SKIP, "nothing followed")]
    if block.get("postings", 0) == 0:
        failed = block.get("failed") or 0
        detail = "collect saved no local posting" + (f" ({failed} failed)" if failed else "")
        return [Line("collect", "feeds", FAIL, detail)]
    lines = [Line("collect", "feeds", PASS, f"{block['postings']} postings from {len(followed)} employers")]
    if share is not None:
        status = PASS if share >= floor else FAIL
        lines.append(Line("collect", "local share", status, f"{share:.2f} (floor {floor:.2f})"))
    return lines


def _failure_reasons(block: dict) -> str:
    """` (reason; other reason)`: the distinct errors the match block kept, none for an older record."""
    reasons = list(dict.fromkeys(f["error"] for f in block.get("failures") or [] if f.get("error")))
    return f" ({'; '.join(reasons[:3])})" if reasons else ""


def judge_match(block: dict, languages: list[str], *, stubbed: bool = False) -> list[Line]:
    note = " (scoring stubbed)" if stubbed else ""
    if block.get("scored", 0) == 0:
        return [Line("match", "score", FAIL, "scored nothing" + note)]
    if block.get("failed"):
        return [Line("match", "score", FAIL,
                     f"{len(block['failed'])} postings failed to score{_failure_reasons(block)}{note}")]
    language = (block.get("passes") or {}).get("language") or {}
    counts, dropped = language.get("languages") or {}, language.get("dropped", 0)
    accepted = {_LANGUAGE_CODES.get(l, l) for l in languages}
    if counts and not counts.get("en"):
        return [Line("match", "language", FAIL, "no English ad in the run" + note)]
    for code in sorted(accepted - {"en"}):
        mine = counts.get(code, 0)
        foreign = sum(n for c, n in counts.items() if c not in accepted)
        if mine and max(0, dropped - foreign) > mine / 2:
            return [Line("match", "language", FAIL, f"{code} ads mostly dropped by the language pass{note}")]
    return [Line("match", "score", PASS, f"{block['scored']} scored{note}")]


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def verdict(lines: list[Line]) -> str:
    return FAIL if any(l.status == FAIL for l in lines) else PASS


def exit_code(lines: list[Line]) -> int:
    return 1 if verdict(lines) == FAIL else 0


def render_markdown(row: str, day: str, lines: list[Line]) -> str:
    out = [f"# Country smoke: {row} ({day})", "", "| step | name | status | detail |", "|---|---|---|---|"]
    out += [f"| {l.step} | {l.name} | {l.status} | {l.detail.replace('|', '/')} |" for l in lines]
    return "\n".join(out) + f"\n\nVerdict: {verdict(lines)}\n"


def report_path(base: Path, cc: str, day: str) -> Path:
    return Path(base) / cc / f"smoke-{day}.md"


def clear_report(base: Path, cc: str, day: str) -> None:
    """Remove the day's earlier report, so a run that stops half way leaves none rather than a stale one."""
    report_path(base, cc, day).unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Sandbox state
# --------------------------------------------------------------------------- #

_STATE_FILES = ("scrape_state.json", "discovery/linkedin.json")


def seed_discover_pace(jobs_dir: Path, budget: int) -> None:
    """Set the LinkedIn request budget for the next discover (the floor is 10), keeping the rest state."""
    path = Path(jobs_dir) / "discovery" / "linkedin.json"
    if not path.exists() and (Path(jobs_dir) / "linkedin_discovery.json").exists():
        path = Path(jobs_dir) / "linkedin_discovery.json"  # an older sandbox: `load` migrates it
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state["pace"] = {**(state.get("pace") or {}), "budget": budget, "factor": 1}
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def carry_over(previous: Path, current: Path) -> None:
    """Carry only the rests (`pushback_at`) of an earlier sandbox into a new one. The watermarks and the rest of the
    state stay behind: a board is read whole each run, so a repeat run does not report 0 for a healthy board."""
    for name in _STATE_FILES:
        src = Path(previous) / "jobs" / name
        try:
            state = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if name == "scrape_state.json":
            kept = {site: {"pushback_at": v["pushback_at"]} for site, v in state.items()
                    if isinstance(v, dict) and v.get("pushback_at")}
        else:
            kept = {"pushback_at": state["pushback_at"]} if state.get("pushback_at") else {}
        if kept:
            dst = Path(current) / "jobs" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(kept, indent=2), encoding="utf-8")


def write_config(profile_dir: Path, row: dict, *, discovery: bool) -> None:
    path = Path(profile_dir) / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.update(location=row["location"], languages=row["languages"], search_keywords=row["keywords"],
                  linkedin_discovery=discovery, profession_discovery=discovery,
                  jobbsafari_discovery=discovery, hellowork_discovery=discovery,
                  prescreen_top_n=5)
    if row.get("role_targets"):  # a profession row (#427) is searched with its own targets and topic terms
        config["role_targets"] = row["role_targets"]
    if row.get("topic_terms"):
        config["topic_terms"] = row["topic_terms"]
    else:
        config.pop("topic_terms", None)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def fresh_sandbox(path: Path, row: dict, *, discovery: bool) -> Path:
    """A new sandbox at *path* (the old one is removed after its rest state moved over)."""
    previous = None
    if path.exists():
        previous = path.with_name(path.name + ".prev")
        shutil.rmtree(previous, ignore_errors=True)
        path.rename(previous)
    sandbox.install(path)
    if previous is not None:
        carry_over(previous, path)
        shutil.rmtree(previous, ignore_errors=True)
    write_config(workspace.PROFILE_DIR, row, discovery=discovery)
    return path


def _fake_score_postings(postings, *, on_result=None, **kwargs):
    results = {}
    for posting in postings:
        result = {"score": 0.3, "score_reason": "stubbed", "matching_skills": [], "missing_skills": [],
                  "scored_by": scorer.DEFAULT_MODEL, "scored_at": datetime.now(timezone.utc).isoformat()}
        results[posting["id"]] = result
        if on_result is not None:
            on_result(posting["id"], result)
    return results, []


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def _guard(lines: list[Line], step: str, call):
    """Run *call*; an exception becomes a FAIL line for the step instead of ending the run."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - one broken step must not hide the others
        lines.append(Line(step, "run", FAIL, f"{type(exc).__name__}: {exc}"))
        return None


_STUCK: list[threading.Thread] = []   # step threads that outlived their cap (a thread cannot be killed)


def _timed(seconds: float, call):
    """Run *call* on a daemon thread for at most *seconds* (#599). Returns ``(finished, result)``; an exception
    in *call* is raised here. A call that hits the cap keeps running in the background (`_STUCK`): a host that
    accepts a connection and then stalls must not end the whole run, but the thread cannot be stopped."""
    box: dict = {}

    def target():
        try:
            box["result"] = call()
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        _STUCK.append(thread)
        return False, None
    if "error" in box:
        raise box["error"]
    return True, box.get("result")


def _blocked(lines: list[Line], step: str) -> bool:
    """A SITE-SIDE skip line when an earlier step is still running: it holds the ledger lock."""
    if any(t.is_alive() for t in _STUCK):
        lines.append(Line(step, "run", SITE_SIDE, "skipped: an earlier step is still running (see above)"))
        return True
    return False


def _guard_timed(lines: list[Line], step: str, seconds: float, call, stopped):
    """`_guard` with a cap of *seconds*; a step that hits it gets the SITE-SIDE line ``stopped()`` words."""
    def run():
        finished, result = _timed(seconds, call)
        if not finished:
            lines.append(Line(step, "run", SITE_SIDE, stopped()))
        return result

    return _guard(lines, step, run)


def _known_names() -> set[str]:
    """The employers the sandbox's companies.json holds now (before follow: profile.example's)."""
    return {c.name for c in companies.load(workspace.PROFILE_DIR)}


def _followed_names(limit: int, before: set[str], *, everyone: bool = False) -> list[str]:
    """The first *limit* followed employers this run's follow added. The ones in *before* are profile.example's
    (Danish, `manual`): collecting them would never read a feed of the country under test. `found_via` cannot
    tell them apart, since an employer queued only by a source it does not name is recorded as `manual` too."""
    items = companies.load(workspace.PROFILE_DIR)
    found = [c.name for c in items if c.status == "followed" and c.name not in before]
    return found if everyone else found[:limit]


def _match(lines: list[Line], row: dict, args) -> None:
    if _blocked(lines, "match"):
        return
    block = _guard(lines, "match", lambda: find_cmd._find_core("match", dry_run=False)["match"])
    if block is not None:
        lines.extend(judge_match(block, row["languages"], stubbed=args.stub_scoring))


def run_primary(name: str, row: dict, args, base: Path, lines: list[Line]) -> Path:
    """search, discover, follow, collect for *row*; returns its sandbox (match is run by the caller)."""
    path = fresh_sandbox(base / row["cc"] / f"smoke-sandbox-{name}", row, discovery=True)

    search = _guard(lines, "search", lambda: find_cmd._find_core("search")["search"])
    if search is not None:
        lines.extend(judge_search(search))

    seed_discover_pace(workspace.JOBS_DIR, args.budget)
    discover = _guard(lines, "discover", lambda: find_cmd._find_core("discover")["discover"])
    if discover is not None:
        lines.extend(judge_discover(discover))

    queued = cap_queue(workspace.JOBS_DIR, args.follow)
    if queued > args.follow > 0:
        lines.append(Line("follow", "sample", PASS, f"followed {args.follow} of {queued} queued employers"))
    cap = args.step_timeout
    dry = _guard_timed(lines, "follow", cap, lambda: find_cmd._find_core("follow", dry_run=True)["follow"],
                       lambda: f"dry run stopped after {cap:.0f} s: employer hosts did not answer")
    if dry is not None:
        lines.extend(judge_follow(dry))
    before = _known_names()
    if not _blocked(lines, "follow"):
        _guard_timed(lines, "follow", cap, lambda: find_cmd._find_core("follow"),
                     lambda: f"stopped after {cap:.0f} s, {len(_followed_names(0, before, everyone=True))} employers done "
                             "(employer hosts did not answer)")

    names = _followed_names(args.collect, before)
    collect = None
    if names and not _blocked(lines, "collect"):
        collect = _guard_timed(lines, "collect", cap, lambda: find_cmd._find_core("collect", companies=names)["collect"],
                               lambda: f"stopped after {cap:.0f} s, no postings counted")
    share = local_share(search, collect)
    if names and collect is None:
        return path
    lines.extend(judge_collect(collect or {}, names, share, row["floor"]))
    return path


def run_country(cc: str, mode: str, args, base: Path, profession: str | None = None) -> list[tuple[str, list[Line]]]:
    """The sections of a run. With *profession*, only that profession's row of *cc* (searched, followed, collected
    and matched alone); without it, the country's plain rows, never the profession ones."""
    if profession is not None:
        name = f"{cc}-{profession}"
        row = PROFILES[name]
        lines: list[Line] = []
        run_primary(name, row, args, base, lines)
        _match(lines, row, args)
        return [(name, lines)]
    rows = {n: r for n, r in PROFILES.items() if r["cc"] == cc and "profession" not in r}
    english = next(((n, r) for n, r in rows.items() if r["languages"] == ["English"]), None)
    local = next(((n, r) for n, r in rows.items() if r["languages"] != ["English"]), None)
    sections = []
    if mode in ("local", "both") and local is None:
        sections.append((f"{cc} (local)", [Line("setup", "local language", SKIP, "no supported local language")]))
    primary = english if mode in ("en", "both") and english else local if mode == "local" else None
    if primary is None:
        return sections
    name, row = primary
    lines: list[Line] = []
    sandbox_path = run_primary(name, row, args, base, lines)
    followed_state = (workspace.PROFILE_DIR / "companies.json")
    second = local if mode == "both" and local is not None else None
    if second is not None:
        second_name, second_row = second
        second_lines: list[Line] = []
        second_path = fresh_sandbox(base / cc / f"smoke-sandbox-{second_name}", second_row, discovery=False)
        copy_jobs(sandbox_path, second_path)
        if followed_state.exists():
            shutil.copy2(followed_state, second_path / "profile" / "companies.json")
        _match(second_lines, second_row, args)
        sections.append((second_name, second_lines))
        sandbox.install(sandbox_path)  # back to the English sandbox for its own match
    _match(lines, row, args)
    sections.insert(0, (name, lines))
    return sections


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="country_smoke", description="Live smoke run of a whole country.")
    parser.add_argument("cc", help="country code, one of: " + ", ".join(sorted({r["cc"] for r in PROFILES.values()})))
    parser.add_argument("--langs", choices=["en", "local", "both"], default="both")
    parser.add_argument("--profession", metavar="NAME", help="run one profession's profile alone (#427): "
                        + ", ".join(sorted(r["profession"] for r in PROFESSION_ROWS.values())))
    parser.add_argument("--stub-scoring", action="store_true", help="do not call claude to score")
    parser.add_argument("--collect", type=int, default=3, metavar="N", help="followed employers to collect (3)")
    parser.add_argument("--follow", type=int, default=40, metavar="N",
                        help="queued employers to follow, sampled across the sources (40, 0 = all)")
    parser.add_argument("--step-timeout", type=float, default=900, metavar="S",
                        help="seconds a follow or collect step may take before it is recorded as SITE-SIDE and the run "
                             "goes on (900)")
    parser.add_argument("--budget", type=int, default=10, metavar="N", help="LinkedIn request budget (10, the floor)")
    parser.add_argument("--dir", type=Path, default=ROOT / "thoughts" / "country", help="where reports and sandboxes go")
    args = parser.parse_args(argv)

    known = sorted({r["cc"] for r in PROFILES.values()})
    if args.cc not in known:
        sys.stderr.write(f"unknown country {args.cc!r}. Known countries: {', '.join(known)}\n")
        return 2

    if args.profession is not None:
        names = {r["profession"] for r in PROFESSION_ROWS.values() if r["cc"] == args.cc}
        if args.profession not in names:
            sys.stderr.write(f"unknown profession {args.profession!r} for {args.cc}. Known: {', '.join(sorted(names))}\n")
            return 2

    if args.stub_scoring:
        scorer.score_postings = _fake_score_postings
        common._claude_available = lambda: True

    _STUCK.clear()
    day = date.today().isoformat()
    clear_report(args.dir, args.cc, day)
    sections = run_country(args.cc, args.langs, args, args.dir, args.profession)
    path = report_path(args.dir, args.cc, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(render_markdown(n, day, ls) for n, ls in sections), encoding="utf-8")

    all_lines = [l for _, ls in sections for l in ls]
    for line in all_lines:
        sys.stdout.write(f"{line.status:9} {line.step}/{line.name}: {line.detail}\n")
    sys.stdout.write(f"Report: {path}\nVerdict: {verdict(all_lines)}\n")
    return exit_code(all_lines)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
