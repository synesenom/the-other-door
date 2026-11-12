"""`jobs query`: counts and the best rows over the postings and the ledger, by filter (#339).

Pure reading under jobs/ (no lock, no writes): the question "how many Teamtailor postings this month?"
or "average score of the Danish ads in September" that no other tool answers. The `query_jobs` tool
is the same core; `ask` lets its model call it.
"""

from collections import Counter
from datetime import date
from pathlib import Path

import click

from door.commands import _common as common
from door.core import selection, tracker as tracker_mod, workspace


def _day(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{name} must be a date like 2026-09-01, not {value!r}") from None


def _when(posting: dict) -> str:
    return str(posting.get("scraped_at") or posting.get("posted_at") or "")[:10]


def _has_materials(jobs_dir: Path, job_id: str) -> bool:
    out = jobs_dir / "output" / job_id
    return (out / "cv.pdf").exists() and (out / "cover_letter.pdf").exists()


def _query_core(
    *,
    since: str | None = None,
    until: str | None = None,
    site: str | None = None,
    company: str | None = None,
    status: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    language: str | None = None,
    has_materials: bool | None = None,
    limit: int = 10,
    jobs_dir: Path | None = None,
) -> dict:
    """Postings matching every filter given, counted and summarised. Never prints, never writes.

    Dates are days (`2026-09-01`) compared with when door first saw the posting (`scraped_at`, else
    `posted_at`), both ends included. `company` matches part of the name, any case; `status` is a ledger
    status (`unapplied` for the untracked) or `interview` for any round.

    Returns:
        ``{"count", "average_score" (of the scored ones, None when none), "by_site", "by_company",
        "by_status", "by_month" (YYYY-MM by when first seen), "rows": [{"id", "title", "company",
        "score", "status", "site", "scraped_at", "posted_at"}, ...]}``, the rows best score first.

    Raises:
        ValueError: a date that is not one.
    """
    jobs_dir = Path(jobs_dir or workspace.JOBS_DIR)
    start, end = _day(since, "since"), _day(until, "until")
    ledger = tracker_mod.ApplicationTracker(jobs_dir / "applications.json")

    def status_of(p: dict) -> str:
        return ledger.get_status(p.get("id", "")) or "unapplied"

    def keep(p: dict) -> bool:
        day = _when(p)
        if start and (not day or day < start):
            return False
        if end and (not day or day > end):
            return False
        if site and p.get("source") != site:
            return False
        if company and company.lower() not in str(p.get("company", "")).lower():
            return False
        if status:
            s = status_of(p)
            if not (s == status or (status == "interview" and s.startswith("interview:"))):
                return False
        score = p.get("score")
        if min_score is not None and (score is None or score < min_score):
            return False
        if max_score is not None and (score is None or score > max_score):
            return False
        if language and str(p.get("language") or "").lower() != language.lower():
            return False
        if has_materials is not None and _has_materials(jobs_dir, p.get("id", "")) != has_materials:
            return False
        return True

    found = [p for p in selection.read_postings(jobs_dir) if keep(p)]
    scores = [p["score"] for p in found if isinstance(p.get("score"), (int, float))]
    best = sorted(found, key=lambda p: (p.get("score") is None, -(p.get("score") or 0)))
    return {
        "count": len(found),
        "average_score": round(sum(scores) / len(scores), 2) if scores else None,
        "by_site": dict(Counter(p.get("source", "") for p in found).most_common()),
        "by_company": dict(Counter(p.get("company", "") for p in found).most_common(10)),
        "by_status": dict(Counter(status_of(p) for p in found).most_common()),
        "by_month": dict(sorted(Counter(_when(p)[:7] for p in found if _when(p)).items())),
        "rows": [
            {
                "id": p.get("id", ""), "title": p.get("title", ""), "company": p.get("company", ""),
                "score": p.get("score"), "status": status_of(p), "site": p.get("source", ""),
                "scraped_at": p.get("scraped_at"), "posted_at": p.get("posted_at"),
            }
            for p in best[: max(0, limit)]
        ],
    }


@click.command("query")
@click.option("--since", default=None, help="First seen on or after this day (2026-09-01).")
@click.option("--until", default=None, help="First seen on or before this day.")
@click.option("--site", default=None, help="Only postings from this site (jobindex, teamtailor, ...).")
@click.option("--company", default=None, help="Only companies whose name contains this.")
@click.option("--status", default=None, help="A status (applied, rejected, ...), unapplied for untracked, or interview for any round.")
@click.option("--min-score", "min_score", type=float, default=None, help="Only postings scoring at least this.")
@click.option("--max-score", "max_score", type=float, default=None, help="Only postings scoring at most this.")
@click.option("--language", default=None, help="Only ads in this language (a code: en, da, hu).")
@click.option("--has-materials/--no-materials", "has_materials", default=None, help="Only postings with (or without) a prepared CV and letter.")
@click.option("--limit", type=click.IntRange(min=0), default=10, help="How many of the best to list (default 10).")
def query(since, until, site, company, status, min_score, max_score, language, has_materials, limit):
    """Count and list postings by filter: site, company, status, score, language, dates.

    Read only. The counts by site, company, status and month, the average score, and the best
    postings by title and company. Name a job to the other commands by those words."""
    try:
        r = _query_core(since=since, until=until, site=site, company=company, status=status, min_score=min_score,
                        max_score=max_score, language=language, has_materials=has_materials, limit=limit,
                        jobs_dir=workspace.JOBS_DIR)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None
    console = common._console()
    head = f"{r['count']} {'posting' if r['count'] == 1 else 'postings'}"
    if r["average_score"] is not None:
        head += f", average score {r['average_score']:.2f}"
    console.print(head)
    for label, key in (("By site", "by_site"), ("By status", "by_status"), ("By month", "by_month")):
        if r[key]:
            console.print(f"{label}: " + ", ".join(f"{k} {v}" for k, v in r[key].items()))
    for row in r["rows"]:
        score = f"{row['score']:.2f}" if isinstance(row["score"], (int, float)) else "  — "
        console.print(f"  {score}  {row['title']} · {row['company']}  ({row['status']})")
