"""The inventory of what The other door stores (#56): every file under `profile/` and `jobs/`, with the model or
format that describes it and who owns it.

The `data-migrator` agent diffs from this list between two releases (a model or format that changed, a file that moved
or was renamed, a code-owned file that changed) to write the upgrade steps of `core/migrations.py`; the coverage test of
#57 reads it too. `tests/core/test_stored_unit.py` fails when a writer stores a file this list does not name: a new
stored file is a line here, in the same change.

A pattern is a path relative to the data folder (`HOME`) in forward slashes: `*` is one path segment's text, a trailing `/**`
anything below that folder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# kind: what the file is to the user's data.
CONFIG = "config"          # the user's settings, edited by hand or by a tool
DATA = "data"              # the user's own content (CV, stories, photo)
LEDGER = "ledger"          # state the pipeline keeps between runs
RECORD = "record"          # written once, read later (a posting, a run, a report)
GENERATED = "generated"    # materials made for a job
CODE_OWNED = "code-owned"  # ships with the code; a file here is the user's own override
SCRATCH = "scratch"        # a working copy a command leaves
TRANSIENT = "transient"    # exists while something runs
LOCAL = "local"            # this computer's only: never exported or synced


@dataclass(frozen=True)
class Stored:
    pattern: str
    kind: str
    model: str   # the model, schema or format that describes it
    note: str = ""


INVENTORY: tuple[Stored, ...] = (
    # --- profile/ ---
    Stored("profile/config.json", CONFIG, "door.core.profile_loader.Profile (extra=forbid)"),
    Stored("profile/cv.md", DATA, "Markdown CV: `## ` sections (door.core.cv_sections); each section's kind is read by door.core.cv_read, not stored in the file"),
    Stored("profile/companies.json", LEDGER, "door.core.employers.companies: {version: 1, companies: [entry]}", "has its own internal version"),
    Stored("profile/story_bank.md", DATA, "door.tailoring.story_bank.StoryBank: one `##` story per CARL (Context, Action, Result, Learning)"),
    Stored("profile/photo.jpg", DATA, "JPEG written by door.core.photo.save (EXIF dropped, scaled)"),
    Stored("profile/cv.template.html", CODE_OWNED, "HTML page, CSS and fonts for the CV (the body goes where <<body>> stands)", "ships as profile.example/cv.template.html; a file in profile/ overrides it"),
    Stored("profile/cover-letter.template.html", CODE_OWNED, "HTML page, CSS and fonts for the letter", "ships as profile.example/; a file in profile/ overrides it"),
    Stored("profile/*.template.tex", CODE_OWNED, "a LaTeX template of an older version, kept and never read", "a browser cannot print it; the HTML template is used instead"),
    Stored("profile/fonts/**", CODE_OWNED, "TrueType font files and licences the templates load from /fonts/", "ships as profile.example/fonts/; a profile/fonts/ with .ttf files overrides it"),
    Stored("profile/cv.draft.md", SCRATCH, "draft_cv's proposal, Markdown"),
    Stored("profile/cv.md.bak", SCRATCH, "the CV before the last save_cv"),
    Stored("profile/.enrich_proposals.json", SCRATCH, "enrich's pending proposals"),
    Stored("profile/.data_version", LEDGER, "door.core.migrations: `<major>.<n>`, the profile's data version"),
    Stored("profile/.search_terms_stale", SCRATCH, "empty marker: a saving `keywords` call started and did not finish (door.commands.keywords)"),
    Stored("profile/.upgrading", TRANSIENT, "door.core.migrations: the backup's path while an upgrade runs; left out of export"),
    # --- jobs/ ledgers ---
    Stored("jobs/history.json", LEDGER, "door.core.jobs.history: {job_id: entry}"),
    Stored("jobs/applications.json", LEDGER, "door.core.jobs.tracker: {job_id: {status, updated_at, notes?, materials?, history}}"),
    Stored("jobs/last_review.json", LEDGER, "{reviewed_at, seen}"),
    Stored("jobs/scrape_state.json", LEDGER, "door.core.jobs.freshness: {site: {last_success, pushback_at?}}"),
    Stored("jobs/candidates.json", LEDGER, "door.core.jobs.candidates: {company_key: {name, links, titles, sources, first_seen, last_seen}}"),
    Stored("jobs/discovery/*.json", LEDGER, "door.core.jobs.discovery_state: one file per discovery source"),
    Stored("jobs/skill_aliases.json", LEDGER, "door.core.jobs.skill_aliases: {variant: canonical | null}"),
    Stored("jobs/salary.json", LEDGER, "door.core.salary"),
    Stored("jobs/.tailor/**", TRANSIENT, "door.commands.prepare: the posting copy the tailor reads (posting.json) and the agent definitions handed to claude -p (agents.json), one folder per job", "removed when the tailor ends"),
    Stored("jobs/.data_version", LEDGER, "door.core.migrations: `<major>.<n>`, the jobs folder's data version"),
    Stored("jobs/.upgrading", TRANSIENT, "door.core.migrations: the backup's path while an upgrade runs; left out of export"),
    # --- jobs/ records ---
    Stored("jobs/runs/*.json", RECORD, "a find run: one block per step (door.pipeline.*), see core/jobs/runs.py"),
    Stored("jobs/runs/latest.log", RECORD, "one summary line per run"),
    Stored("jobs/postings/*/*/*.json", RECORD, "door.core.models.JobPosting, plus the score fields the match step adds"),
    Stored("jobs/market/report-*.md", RECORD, "door.commands.market's report"),
    Stored("jobs/drift/**", RECORD, "the raw response doctor saved for a scraper that no longer fits its site"),
    # --- jobs/output/<job_id>/ ---
    Stored("jobs/output/*/posting.json", GENERATED, "a copy of the JobPosting the materials were made for"),
    Stored("jobs/output/*/cv.html", GENERATED, "the tailor's CV: a body fragment in the closed vocabulary of render/html_guard"),
    Stored("jobs/output/*/cover_letter.html", GENERATED, "the tailor's cover letter: a body fragment"),
    Stored("jobs/output/*/*.html.bak", GENERATED, "the version before the last revise"),
    Stored("jobs/output/*/*.tex", GENERATED, "a CV or letter of an older version (LaTeX), kept and never read: prepare it again to revise"),
    Stored("jobs/output/*/*.tex.bak", GENERATED, "the version before the last revise, of an older version, kept and never read"),
    Stored("jobs/output/*/*.pdf", GENERATED, "compiled by compile"),
    Stored("jobs/output/*/*.png", GENERATED, "page images compile renders for the tailor"),
    Stored("jobs/output/*/photo.*", GENERATED, "the profile's photo, copied beside the page for the printed CV"),
    Stored("jobs/output/*/facts.json", GENERATED, "door.tailoring.facts: what cv.md and the story bank do not back, with the sha256 of the inputs it was asked for (the same inputs are not asked again)"),
    Stored("jobs/output/*/.facts_rounds", GENERATED, "door.commands.check_facts: the fact check rounds used in this prepare run, a number", "cleared when a fresh tailor run starts"),
    Stored("jobs/output/*/sent/**", GENERATED, "the materials as sent, with their sha256 in the ledger"),
    Stored("jobs/output/*/*.json", GENERATED, "other notes the tailor or prepare leaves for the job"),
    # --- jobs/ ---
    Stored("jobs/usage.jsonl", LOCAL, "door.core.usage: one line per claude call", "this computer's only; left out of export and Drive"),
    Stored("jobs/.lock", TRANSIENT, "door.core.lock: the OS lock file"),
    Stored("jobs/.lock.json", TRANSIENT, "door.core.lock: who holds it"),
    Stored("jobs/.progress.json", TRANSIENT, "door.core.progress: the running find's board"),
    # --- not under profile/ or jobs/ ---
    Stored("backups/**", LOCAL, "what an import or an upgrade replaced"),
    Stored("logs/**", LOCAL, "door.core.problem_log"),
    Stored(".door-import-*.part/**", TRANSIENT, "door.core.sync.archive: an import being unpacked beside profile/ and jobs/, swapped in when whole"),
    Stored(".mcp.json", LOCAL, "generated by workspace.ensure_mcp_config"),
    Stored(".serve/**", LOCAL, "door.core.phone.phone: the phone server's state"),
    Stored(".style/preview/**", LOCAL, "door.commands.cv_style_sample: `<hash>.png`, page 1 of the CV in a chosen style (#465: made again when anything it was printed from changes)"),
    Stored(".cv_read/**", LOCAL, "door.core.cv_read: `<sha256>.json`, the model's reading of cv.md (#430: made again when its prompt version changes)"),
)


def _regex(pattern: str) -> re.Pattern:
    """`*` is the text of one segment; a trailing `/**` is anything below that folder."""
    below = pattern.endswith("/**")
    segments = (pattern[:-3] if below else pattern).split("/")
    rx = "/".join(re.escape(segment).replace(r"\*", "[^/]*") for segment in segments)
    return re.compile(rx + ("/.+" if below else ""))


_COMPILED = [(entry, _regex(entry.pattern)) for entry in INVENTORY]


def named(relative: str) -> Stored | None:
    """The inventory entry a path (relative to the data folder, forward slashes) falls under, or None."""
    relative = relative.replace("\\", "/")
    for entry, rx in _COMPILED:
        if rx.fullmatch(relative):
            return entry
    return None


def unnamed(home: Path, roots: tuple[str, ...] = ("profile", "jobs")) -> list[str]:
    """The files under ``home/<root>`` the inventory does not name (relative paths, sorted)."""
    home = Path(home)
    missing = []
    for root in roots:
        base = home / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                relative = path.relative_to(home).as_posix()
                if named(relative) is None:
                    missing.append(relative)
    return missing
