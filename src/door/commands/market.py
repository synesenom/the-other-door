"""`market`: what the scraped ads ask for, counted over a window and written to
`jobs/market/report-<date>.md`. Plain counting; the only LLM call is one Haiku
question per 200 skill names not yet in `jobs/skill_aliases.json`.

Raw ads feed the volume and the repeat companies; scored ads feed skills and near
misses; the above-`min_score` matches feed the uncovered titles. (`flags` is not
persisted by the scorer, so it is not read.) Skill names are counted as written,
case-insensitively after being mapped through `jobs/skill_aliases.json`
(`{variant: canonical | null}`, hand-editable, a hand edit always wins; `null` marks a
name that is not a skill and drops it).
"""

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from door.commands import _common as common
from door.core import companies as companies_store
from door.core import claude_cli, lock, selection, skill_aliases, workspace
from door.core.utils import write_json_atomic
from door.matching import title_fit

_TREND_MIN = 50  # scored ads needed in both windows before a trend means anything
_NEAR_BAND = 0.15
_SKILLS, _NEAR_ROWS, _TITLES, _COMPANIES = 15, 10, 10, 10
_NOT_SCORED = ("duplicate", "excluded", "prefilter:", "prescreen:")
_CHUNK = 200  # names per Haiku call
_CONTEXT = 300  # existing canonical names shown to the model
_DEFAULT_MODEL = "haiku"
_SYSTEM_PROMPT = (
    "You group skill names taken from job ads. Input is JSON: `names` (the names to "
    "classify) and `known_canonical` (canonical names already in use). For every name in "
    "`names` answer one group {variant, canonical, skill}, with `variant` copied exactly.\n"
    "- Group spellings, abbreviations, translations and parenthetical detail of the same "
    "skill under one canonical name (\"Microsoft Excel\", \"Excel (pivot tables)\" -> \"Excel\"). "
    "Reuse a name from `known_canonical` when it is the same skill.\n"
    "- Never merge different tools, methods or qualifications (SAP is not Oracle; Excel is not "
    "Power BI; a forklift licence is not a truck licence).\n"
    "- Set `skill` to false, with an empty `canonical`, for anything that is not a skill: a "
    "location or work arrangement (\"Copenhagen hybrid location\"), a spoken language "
    "(\"Fluent English\"), seniority or scope (\"Lead or manager scope\").\n"
    "- Keep canonical names short, in the usual written form of the tool."
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "variant": {"type": "string"},
                    "canonical": {"type": "string"},
                    "skill": {"type": "boolean"},
                },
                "required": ["variant", "canonical", "skill"],
            },
        }
    },
    "required": ["groups"],
}


def _when(posting: dict) -> datetime | None:
    """`posted_at`, else `scraped_at`, as an aware UTC datetime (naive reads as UTC); None when neither parses."""
    for key in ("posted_at", "scraped_at"):
        value = posting.get(key)
        if not value:
            continue
        try:
            when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return None


def _is_duplicate(posting: dict) -> bool:
    return bool(posting.get("duplicate_of")) or str(posting.get("score_reason") or "").startswith("duplicate")


def _is_scored(posting: dict) -> bool:
    """The scorer read it (``scored_by`` set): the hard zeros of the passes before it
    (language, no description, prefilter, ...) carry no skills and stay out."""
    if posting.get("score") is None or not posting.get("scored_by") or _is_duplicate(posting):
        return False
    return not str(posting.get("score_reason") or "").startswith(_NOT_SCORED)


def _split_windows(postings, now: datetime, days: int) -> tuple[list[dict], list[dict], list[dict]]:
    """(current raw, current scored, previous scored); duplicates dropped, each posting once."""
    start, prev_start = now - timedelta(days=days), now - timedelta(days=2 * days)
    cur_raw, cur_scored, prev_scored = [], [], []
    for posting in postings:
        if _is_duplicate(posting):
            continue
        when = _when(posting)
        if when is None:
            continue
        if start <= when <= now:
            cur_raw.append(posting)
            if _is_scored(posting):
                cur_scored.append(posting)
        elif prev_start <= when < start and _is_scored(posting):
            prev_scored.append(posting)
    return cur_raw, cur_scored, prev_scored


def _normalise(skills, aliases: dict) -> list[str]:
    """Skill names mapped through `aliases` (case-insensitive): null drops, unknown keeps the
    stripped name, deduped on the lowercase result."""
    out: list[str] = []
    seen: set[str] = set()
    for skill in skills or []:
        name = str(skill).strip()
        if not name:
            continue
        if name.lower() in aliases:
            name = aliases[name.lower()]
            if not name:
                continue
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _unknown_names(scored: list[dict], prev_scored: list[dict], aliases: dict) -> list[str]:
    """Stripped skill names of both windows with no alias entry, once per lowercase form, sorted."""
    found: dict[str, str] = {}
    for p in [*scored, *prev_scored]:
        for key in ("matching_skills", "missing_skills"):
            for skill in p.get(key) or []:
                name = str(skill).strip()
                if name and name.lower() not in aliases:
                    found.setdefault(name.lower(), name)
    return sorted(found.values(), key=str.lower)


def _ask_aliases(unknown: list[str], known: list[str], profile_dir: Path) -> tuple[dict, str | None]:
    """Ask Haiku about `unknown` in chunks. Returns (``{lowercase name: canonical | None}``, warning);
    stops at the first chunk that fails, keeping the earlier ones."""
    new: dict = {}
    context = list(dict.fromkeys(known))
    for start in range(0, len(unknown), _CHUNK):
        chunk = unknown[start:start + _CHUNK]
        payload = json.dumps({"names": chunk, "known_canonical": context[:_CONTEXT]}, ensure_ascii=False)
        try:
            answer = claude_cli.ask(_SYSTEM_PROMPT, payload, model=_DEFAULT_MODEL, feature="market_aliases",
                                    schema=_SCHEMA, timeout_s=120, profile_dir=profile_dir)
            groups = answer.get("groups") if isinstance(answer, dict) else None
            if not isinstance(groups, list) or not all(
                isinstance(g, dict) and isinstance(g.get("variant"), str) and isinstance(g.get("canonical"), str)
                and isinstance(g.get("skill"), bool) for g in groups
            ):
                raise claude_cli.ClaudeError("claude's answer has no valid `groups` list")
        except claude_cli.ClaudeError as exc:
            return new, f"skill names not grouped for some ads ({exc}); they are counted as written"
        sent = {n.lower(): n for n in chunk}
        for g in groups:
            low = g["variant"].strip().lower()
            if low not in sent or low in new:
                continue
            canonical = g["canonical"].strip()
            new[low] = (canonical or sent[low]) if g["skill"] else None
        for low, name in sent.items():
            new.setdefault(low, name)
        for low in sent:
            canonical = new[low]
            if canonical:
                new.setdefault(canonical.lower(), canonical)
                if canonical not in context:
                    context.append(canonical)
    return new, None


def _normalised_copy(postings: list[dict], aliases: dict) -> list[dict]:
    return [
        {**p, "matching_skills": _normalise(p.get("matching_skills"), aliases),
         "missing_skills": _normalise(p.get("missing_skills"), aliases)}
        for p in postings
    ]


def _tally(scored: list[dict], key: str) -> tuple[Counter, dict[str, str]]:
    """Per-ad counts of a skill list (once per ad), keyed lower-case, plus a display name."""
    counts: Counter = Counter()
    names: dict[str, str] = {}
    for posting in scored:
        seen = {str(s).strip() for s in posting.get(key) or [] if str(s).strip()}
        for skill in seen:
            names.setdefault(skill.lower(), skill)
        for low in {s.lower() for s in seen}:
            counts[low] += 1
    return counts, names


def _count_skills(scored: list[dict], prev_scored: list[dict], *, limit: int = _SKILLS) -> list[dict]:
    """The most requested skills: ``{name, count, share, have, trend}``. `have`: in
    `matching_skills` more often than in `missing_skills`. `trend`: change in count
    against the previous window, None unless both have `_TREND_MIN` scored ads."""
    matching, m_names = _tally(scored, "matching_skills")
    missing, x_names = _tally(scored, "missing_skills")
    names = {**x_names, **m_names}
    total: Counter = Counter()
    for p in scored:
        total.update({str(s).strip().lower() for s in (p.get("matching_skills") or []) + (p.get("missing_skills") or []) if str(s).strip()})
    show_trend = len(scored) >= _TREND_MIN and len(prev_scored) >= _TREND_MIN
    prev_total: Counter = Counter()
    if show_trend:
        for p in prev_scored:
            prev_total.update({str(s).strip().lower() for s in (p.get("matching_skills") or []) + (p.get("missing_skills") or []) if str(s).strip()})
    rows = []
    for low, count in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        rows.append({
            "name": names[low],
            "count": count,
            "share": count / len(scored),
            "have": matching[low] > missing[low],
            "trend": count - prev_total[low] if show_trend else None,
        })
    return rows


def _near_misses(scored: list[dict], min_score: float, *, limit: int = _NEAR_ROWS) -> dict:
    """What kept ads in ``[min_score - 0.15, min_score)`` below the bar: their most common missing skills."""
    low = min_score - _NEAR_BAND
    band = [p for p in scored if low - 1e-9 <= p["score"] < min_score]
    counts, names = _tally(band, "missing_skills")
    rows = [{"skill": names[k], "count": c} for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
    return {"n": len(band), "rows": rows}


def _companies(raw: list[dict], *, limit: int = _COMPANIES) -> list[dict]:
    counts: Counter = Counter()
    names: dict[str, str] = {}
    for p in raw:
        name = str(p.get("company") or "").strip()
        if name:
            names.setdefault(name.lower(), name)
            counts[name.lower()] += 1
    return [{"name": names[k], "count": c} for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if c >= 2][:limit]


def _mark_followed(rows: list[dict], items: list) -> list[dict]:
    """Each row with ``followed``: the employer list has it with status `followed` (names compared as `companies.find` does)."""
    out = []
    for row in rows:
        found = companies_store.find(items, row["name"])
        out.append({**row, "followed": found is not None and found.status == "followed"})
    return out


def _uncovered_titles(matches: list[dict], keywords: list[str], *, limit: int = _TITLES) -> list[dict]:
    """Titles of `matches` containing none of the search keywords (case-insensitive), by frequency."""
    terms = [k.lower() for k in keywords]
    counts: Counter = Counter()
    names: dict[str, str] = {}
    for p in matches:
        title = str(p.get("title") or "").strip()
        if title and not any(t in title.lower() for t in terms):
            names.setdefault(title.lower(), title)
            counts[title.lower()] += 1
    return [{"title": names[k], "count": c} for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def render_markdown(report: dict) -> str:
    c, w = report["counts"], report["window"]
    lines = [
        f"# Market — last {w['days']} days ({c['scraped']} ads scraped, {c['scored']} scored, {c['above_min_score']} above min_score)",
        "",
        "Your slice of the market: only ads your search keywords found on your sites.",
        "",
    ]
    if report.get("warning"):
        lines += [f"Warning: {report['warning']}", ""]
    skills = report["skills"]
    trend = any(s["trend"] is not None for s in skills)
    lines.append("## Most requested skills in scored ads")
    lines.append("")
    lines.append("| Skill | Ads | Share | You have it |" + (" Trend |" if trend else ""))
    lines.append("|---|---|---|---|" + ("---|" if trend else ""))
    for s in skills:
        row = f"| {s['name']} | {s['count']} | {s['share']:.0%} | {'✓' if s['have'] else '✗'} |"
        if trend:
            t = s["trend"]
            row += f" {'=' if not t else f'{t:+d}'} |"
        lines.append(row)
    nm = report["near_misses"]
    lines += ["", f"## Near misses (score min_score−0.15 … min_score): what kept them below your bar", ""]
    for r in nm["rows"]:
        lines.append(f"- {r['skill']}: in {r['count']} of {nm['n']}")
    if not nm["rows"]:
        lines.append("- none")
    titles = ", ".join(f"\"{t['title']}\" ({t['count']})" for t in report["uncovered_titles"]) or "none"
    lines += ["", f"Titles in your matches that no search keyword covers: {titles}"]
    comp = report["companies"]
    comps = ", ".join(
        f"{x['name']} ({x['count']})" + (" ✓ followed" if x["followed"] else "") for x in comp["rows"]
    ) or "none"
    lines += ["", f"Companies posting repeatedly ({comp['population']} ads): {comps}", ""]
    return "\n".join(lines)


def _market_core(days: int = 30, save: bool = True, *, jobs_dir: Path | None = None,
                 profile_dir: Path | None = None, now: datetime | None = None,
                 scored_companies: bool = False) -> dict:
    """Count the ads of the last `days` days.

    Returns ``{"window": {"days", "start", "end"}, "counts": {"scraped", "scored",
    "above_min_score"}, "skills", "near_misses": {"n", "rows"}, "uncovered_titles",
    "companies": {"population": "scraped"|"scored", "rows": [{"name", "count", "followed"}]},
    "warning", "report_path"}``; names are grouped through `jobs/skill_aliases.json`, new ones asked of Haiku
    (`warning`: text when that failed or the file is unreadable, else None); `scored_companies` counts companies over scored ads instead of all scraped ones (`report_path` None unless `save`). Raises ValueError for days < 1.
    """
    if days < 1:
        raise ValueError("--days must be at least 1")
    jobs_dir = Path(jobs_dir if jobs_dir is not None else workspace.JOBS_DIR)
    profile_dir = Path(profile_dir if profile_dir is not None else workspace.PROFILE_DIR)
    now = now or datetime.now(timezone.utc)
    config = common._load_config_or_defaults(profile_dir)
    min_score = config.get("min_score", common._DEFAULT_MIN_SCORE)

    postings = (p for _, p in selection.iter_postings(jobs_dir))
    raw, scored, prev_scored = _split_windows(postings, now, days)

    alias_path = jobs_dir / skill_aliases.FILE
    aliases, warning = skill_aliases.load(alias_path)
    corrupt = warning is not None
    new: dict = {}
    unknown = [] if corrupt else _unknown_names(scored, prev_scored, aliases)
    if unknown:  # outside the lock: the call takes a while
        known = sorted({v for v in aliases.values() if v})
        new, warning = _ask_aliases(unknown, known, profile_dir)

    def build(alias_map: dict, warn: str | None, report_path) -> dict:
        n_scored, n_prev = _normalised_copy(scored, alias_map), _normalised_copy(prev_scored, alias_map)
        matches = [p for p in n_scored if p["score"] >= min_score]
        return {
            "window": {"days": days, "start": (now - timedelta(days=days)).isoformat(), "end": now.isoformat()},
            "counts": {"scraped": len(raw), "scored": len(n_scored), "above_min_score": len(matches)},
            "skills": _count_skills(n_scored, n_prev),
            "near_misses": _near_misses(n_scored, min_score),
            "uncovered_titles": _uncovered_titles(matches, title_fit.keywords(config)),
            "companies": {
                "population": "scored" if scored_companies else "scraped",
                "rows": _mark_followed(_companies(n_scored if scored_companies else raw), companies_store.load(profile_dir)),
            },
            "warning": warn,
            "report_path": report_path,
        }

    if not save and not new:
        return build(aliases, warning, None)
    path = jobs_dir / "market" / f"report-{now.date().isoformat()}.md"
    try:
        with lock.ledger_lock(jobs_dir, "market"):
            merged = aliases
            if new:  # a hand edit made meanwhile wins over what was just generated
                existing, _ = skill_aliases.load(alias_path)
                merged = {**new, **existing}
                write_json_atomic(alias_path, dict(sorted(merged.items())))
            report = build(merged, warning, str(path) if save else None)
            if save:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_markdown(report), encoding="utf-8")
    except lock.LockHeldError as exc:
        busy = f"another run of The other door holds the lock ({exc}); skill groups and report not saved"
        return build({**new, **aliases}, f"{warning}; {busy}" if warning else busy, None)
    return report


@click.command("market")
@click.option("--days", default=30, show_default=True, type=int, help="Window length in days.")
@click.option("--scored-companies", is_flag=True, help="Count repeat companies over scored ads only (default: all scraped ads).")
@click.option("--save/--no-save", default=True, help="Write the report to jobs/market/ (default: yes).")
def market(days: int, scored_companies: bool, save: bool):
    """What the scraped ads ask for: skills, near misses, uncovered titles, repeat companies. One Haiku call, only for skill names not yet in jobs/skill_aliases.json."""
    try:
        result = _market_core(days, save, scored_companies=scored_companies, jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(render_markdown(result))
    if result["warning"]:
        click.echo(f"Warning: {result['warning']}", err=True)
    if result["report_path"]:
        click.echo(f"Report: {common._display_path(result['report_path'])}")
