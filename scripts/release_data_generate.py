"""Write a sample `profile/` and `jobs/` with a release's own code (#57). Run by `save_release_data.py`, never by hand.

    DOOR_HOME=<empty folder> PYTHONPATH=<worktree of the tag>/src python release_data_generate.py

It uses only what the release has (its stores, models and cores), in the way the release itself wrote them: no
network, no `claude`. The data is made up: a config with every `Profile` key set, followed employers in every
status, a story bank, postings in every state, an application ledger with every status and interview rounds, a
prepared job's output, and a run record. Nothing here may name a real person; addresses are `example.com`.

Written for v0.1.0's API; a later release whose API moved needs this script to follow it, and the next call of
`save_release_data.py` fails loudly (a missing name) rather than saving something that is not the release's.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))  # pdf_utils: small real PDFs

HOME = Path(os.environ["DOOR_HOME"]).resolve()

from door.core import workspace  # noqa: E402

assert workspace.HOME == HOME, f"the release reads {workspace.HOME}, not DOOR_HOME={HOME}"

from door.commands import find as find_cmd  # noqa: E402
from door.commands import profile as profile_cmd  # noqa: E402
from door.commands import stories as stories_cmd  # noqa: E402
from door.core import candidates, companies, discovery_state, freshness, history, tracker  # noqa: E402
from door.core import lock  # noqa: E402
from door.core.models import JobPosting  # noqa: E402
from door.core.profile_loader import Profile  # noqa: E402
from door.tailoring import facts as facts_mod  # noqa: E402

import pdf_utils  # noqa: E402

for _hook in ("pre_acquire_hook", "post_release_hook"):  # never a Google Drive: this is a sample
    if hasattr(lock, _hook):
        setattr(lock, _hook, lambda *args, **kwargs: None)

PROFILE, JOBS = workspace.PROFILE_DIR, workspace.JOBS_DIR


def at(days_ago: int, hour: int = 9) -> datetime:
    """A fixed-looking moment `days_ago` before a base day (the data is a sample: its dates never move)."""
    return datetime(2026, 3, 20, hour, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)


# --------------------------------------------------------------------------- #
# profile/
# --------------------------------------------------------------------------- #
CV = """# Alex Example

alex.example@example.com | Copenhagen

## Summary

Finance controller with nine years in month-end close, forecasting and group reporting.

## Experience

### Senior Controller, Example Industries A/S (2019 - 2024)

- Cut the month-end close from ten to six working days across four entities.
- Built a rolling forecast in Power BI used by 12 managers.

### Financial Analyst, Sample Bank (2015 - 2019)

- Prepared the monthly management accounts for the retail division.

## Skills

Excel, Power BI, SAP, IFRS, SQL

## Education

MSc in Finance, Example University (2015)

## Languages

English (fluent), Danish (fluent)
"""

STORIES = [
    ("Halved the close at Example Industries",
     "The close took ten days and management saw numbers late.",
     "Mapped every task, standardised reconciliations and agreed cut-offs.",
     "Close down to six days; audit adjustments fell from 14 to 3.",
     "The gain came from the teams outside finance."),
    ("Built a rolling forecast at Sample Bank",
     "The annual budget was outdated by spring.",
     "Designed a driver-based forecast and ran workshops in each region.",
     "Accuracy improved from 12 to 4 percent.",
     "Ownership by the managers made it their tool."),
]

FIELDS = {
    "name": "Alex Example",
    "email": "alex.example@example.com",
    "location": "Copenhagen",
    "needs_work_permit": True,
    "cv_template": "profile/cv.template.tex",
    "cv_content": "profile/cv.md",
    "cover_letter_template": "profile/cover-letter.template.tex",
    "photo": "profile/photo.jpg",
    "role_targets": ["Financial Controller", "Head of Finance"],
    "search_keywords": ["financial controller", "head of finance", "group controller"],
    "topic_terms": ["controller", "finance*", "accounting"],
    "remote": "hybrid",
    "linkedin_discovery": True,
    "profession_discovery": True,
    "hellowork_discovery": True,
    "jobbsafari_discovery": True,
    "exclude": {"companies": ["Excluded Corp"], "keywords": ["intern", "unpaid"]},
    "min_score": 0.6,
    "languages": ["English", "Danish"],
    "enrich_sources": ["https://example.com/alex"],
    "claude_config_dir": "~/.claude-example",
    "recheck_after_days": 14,
    "scrape_workers": 4,
    "verify_liveness": True,
    "liveness_expiry_phrases": ["no longer available"],
    "dedup_source_priority": ["jobindex", "thehub"],
    "dedup_similarity_threshold": 0.9,
    "max_postings_per_site": 200,
    "max_pages_per_keyword": 5,
    "condense_max_chars": 3000,
    "prescreen_top_n": 30,
    "prescreen_min": 0.2,
    "translate_titles": False,
    "translate_model": "haiku",
    "max_age_days": 36500,   # a sample's dates never move: the age filter must not drift with the calendar
    "follow_ai_fallback": False,
    "retire_after_days": 60,
    "revise_model": "sonnet",
}


def make_profile() -> None:
    missing = set(Profile.model_fields) - set(FIELDS)
    assert not missing, f"this release has Profile keys the sample does not set: {sorted(missing)}"
    from PIL import Image

    picture = HOME / "picture.png"
    Image.new("RGB", (300, 400), (180, 120, 90)).save(picture)
    profile_cmd._init_core({}, profile_dir=PROFILE, example_dir=workspace.PROFILE_EXAMPLE_DIR)
    profile_cmd._save_cv_core(CV)
    profile_cmd._save_photo_core(str(picture))
    picture.unlink()
    profile_cmd._init_core(FIELDS, profile_dir=PROFILE, example_dir=workspace.PROFILE_EXAMPLE_DIR)
    (PROFILE / "story_bank.md").unlink(missing_ok=True)
    for index, story in enumerate(STORIES):
        stories_cmd._save_story_core(*story, replace_example=index == 0, profile_dir=PROFILE)


def make_companies() -> None:
    now = at(10).isoformat()
    items = [
        companies.Company(
            name="Example Industries A/S", feed=companies.Feed(platform="greenhouse", id="exampleindustries"),
            status="followed", found_via="manual", evidence="Greenhouse board exampleindustries lists open jobs",
            aliases=["Example Industries", "EI Group"], first_seen=now, last_checked=now, last_relevant=at(3).isoformat(),
        ),
        companies.Company(
            name="Sample Bank", feed=companies.Feed(platform="lever", id="samplebank"), status="followed",
            found_via="jobindex", first_seen=now, last_checked=now,
            collect_problem=companies.CollectProblem(at=at(2).isoformat(), outcome="blocked", reason="the feed answered 403"),
        ),
        companies.Company(
            name="Failing Feed Ltd", feed=companies.Feed(platform="teamtailor", id="failing-feed"), status="followed",
            found_via="linkedin", first_seen=now, last_checked=now,
            collect_problem=companies.CollectProblem(at=at(1).isoformat(), outcome="failed", reason="timeout"),
        ),
        companies.Company(
            name="Terms Forbid AB", status="unfollowable", found_via="linkedin", refusal="must_not",
            reason="its terms forbid automated access", evidence="careers page", first_seen=now, last_checked=now,
        ),
        companies.Company(
            name="No Way In Inc", status="unfollowable", found_via="thehub", refusal="cant_yet",
            reason="a platform The other door cannot follow yet", first_seen=now, last_checked=now,
        ),
        companies.Company(
            name="Nowhere Found GmbH", status="unresolved", found_via="ai", reason="no careers page found",
            first_seen=now, last_checked=now,
        ),
        companies.Company(
            name="Quiet Dormant Co", feed=companies.Feed(platform="greenhouse", id="quietdormant"), status="dormant",
            found_via="jobindex", reason="no relevant job for 90 days", first_seen=now, last_checked=now,
            last_relevant=at(120).isoformat(),
        ),
    ]
    companies.save(PROFILE, items)


# --------------------------------------------------------------------------- #
# jobs/
# --------------------------------------------------------------------------- #
def posting(site: str, platform_id: str, title: str, company: str, **fields) -> dict:
    from door.core.models import make_job_id

    job_id = make_job_id(site, platform_id)
    base = {
        "id": job_id, "title": title, "company": company, "location": "Copenhagen",
        "url": f"https://example.com/jobs/{platform_id}",
        "description": f"{title} at {company}. You own the month-end close and the forecast. Excel and IFRS required.",
        "source": site, "scraped_at": at(5), "platform_id": platform_id, "posted_at": at(6),
    }
    return {**base, **fields}


SCORED = dict(scored_by="haiku", scored_at=at(4).isoformat(), matching_skills=["Excel", "IFRS"], missing_skills=["SAP"])

POSTINGS = [
    # (day folder, posting fields, extra keys the match step adds beside the model)
    (5, posting("jobindex", "1001", "Financial Controller", "Example Industries A/S", score=0.92,
                score_reason="strong fit", prescreen_score=0.8, employer="Example Industries A/S",
                description_condensed="Own the close and the forecast.", apply_type="external",
                apply_url="https://example.com/apply/1001", liveness_status="live", **SCORED),
     {"work_permit": "not_mentioned", "language_requirement": "none"}),
    (5, posting("jobindex", "1002", "Head of Finance", "Sample Bank", score=0.85, score_reason="good fit", **SCORED), {}),
    (5, posting("thehub", "2001", "Group Controller", "Failing Feed Ltd", score=0.78, score_reason="fits", apply_type="easy_apply", **SCORED), {}),
    (5, posting("jobindex", "1003", "Finance Business Partner", "Example Industries A/S", score=0.7, score_reason="fits", **SCORED), {}),
    (4, posting("jobindex", "1004", "Business Controller", "Sample Bank", score=0.74, score_reason="fits", **SCORED), {}),
    (4, posting("jobindex", "1005", "Økonomichef", "Nordic Foods A/S", score=0.71, score_reason="fits", apply_type="unknown", **SCORED),
     {"title_en": "Head of Finance (Economy Manager)"}),
    (4, posting("jobindex", "1006", "Controller", "Late Answer ApS", score=0.69, score_reason="fits", **SCORED), {}),
    (3, posting("jobindex", "1007", "Accounting Manager", "Silent Corp", score=0.66, score_reason="fits", **SCORED), {}),
    (3, posting("jobindex", "1008", "Finance Manager", "Another Bank A/S", score=0.9, score_reason="strong fit", **SCORED), {}),
    (3, posting("jobindex", "1009", "Finance Controller", "Dismissed Inc", score=0.68, score_reason="fits", **SCORED), {}),
    # states of a posting that is not a match
    (3, posting("jobindex", "1010", "Accounts Payable Clerk", "Small Shop", score=0.2, score_reason="junior role", **SCORED), {}),
    (3, posting("jobindex", "1011", "Intern Controller", "Excluded Corp", score=0.0, score_reason="prefilter: excluded keyword"), {}),
    (3, posting("jobindex", "1012", "Unscored Controller", "Fresh Ltd"), {}),
    (3, posting("thehub", "2002", "Financial Controller", "Example Industries A/S", score=0.5, score_reason="duplicate", duplicate_of="jobindex.1001"), {}),
    (3, posting("jobindex", "1013", "Senior Controller", "Gone Ltd", score=0.6, score_reason="fits", liveness_status="dead", **SCORED), {}),
    (3, posting("jobindex", "1014", "Controller (suspicious)", "Odd Ltd", score=0.3, score_reason="suspicious ad: fits",
                integrity={"verdict": "suspicious", "findings": [{"kind": "hidden_text", "excerpt": "ignore the instructions"}]}, **SCORED), {}),
]

# job id -> [(status, days ago, notes, at-days-ago or None)]
LEDGER = {
    "jobindex.1002": [("unapplied", 5, None, None), ("prepared", 4, None, None)],
    "jobindex.1003": [("unapplied", 5, "later", None)],
    "jobindex.1004": [("applied", 4, "sent through their site", None)],
    "jobindex.1005": [("applied", 4, None, None), ("interview:screening", 3, "recruiter call went well", None),
                      ("interview:impression", 2, None, None), ("interview:technical", 1, "case study", None), ("offer", 1, "verbal", None)],
    "jobindex.1006": [("applied", 4, None, None), ("interview:screening", 3, None, None), ("rejected", 2, "went with an internal candidate", None)],
    "jobindex.1007": [("applied", 4, None, None), ("interview:assessment", 3, "personality test", None), ("ghosted", 1, None, None)],
    "jobindex.1008": [("applied", 4, None, 6), ("interview:screening", 3, None, None), ("discarded", 2, "withdrew: the role moved to Aarhus", None)],
    "jobindex.1009": [("discarded", 3, "not for me", None)],
    "thehub.2001": [("applied", 4, None, None), ("ghosted", 2, None, None)],
}


def make_postings() -> None:
    store = history.HistoryStore(JOBS / "history.json")
    for days_ago, fields, extra in POSTINGS:
        model = JobPosting(**fields)
        data = {**json.loads(model.model_dump_json()), **extra}
        folder = workspace.day_dir(JOBS, at(days_ago).date().isoformat()) / fields["source"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{fields['id']}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        store.record(fields["id"], fields["platform_id"], fields["url"], fields["source"], now=at(days_ago))
    store.save()


def make_ledger() -> None:
    app = tracker.ApplicationTracker(JOBS / "applications.json")
    for job_id, events in LEDGER.items():
        for status, days_ago, notes, happened in events:
            app.set_status(job_id, status, now=at(days_ago), notes=notes, at=at(happened) if happened else None)
    app.save()


def make_output() -> None:
    """A prepared job (1002) and a sent one (1004, with its `sent/` copy and sha256 in the ledger)."""
    from door.core import utils

    for job_id, sent in (("jobindex.1002", False), ("jobindex.1004", True)):
        folder = JOBS / "output" / job_id
        folder.mkdir(parents=True, exist_ok=True)
        company = "Sample Bank"
        data = next(f for _, f, _ in POSTINGS if f["id"] == job_id)
        (folder / "posting.json").write_text(json.dumps(json.loads(JobPosting(**data).model_dump_json()), indent=2), encoding="utf-8")
        (folder / "cv.tex").write_text(
            "% Keywords: close, forecast, IFRS\n% Tailoring: kept the close story; cut the older role\n"
            f"\\documentclass{{article}}\\begin{{document}}Alex Example, {company}\\end{{document}}\n", encoding="utf-8")
        (folder / "cover_letter.tex").write_text(
            f"\\documentclass{{article}}\\begin{{document}}Dear {company}, I would like to own your close.\\end{{document}}\n", encoding="utf-8")
        pdf_utils.make_pdf(folder / "cv.pdf", ["Alex Example\nSummary\nExperience\nSkills\nEducation\nclose forecast IFRS"])
        pdf_utils.make_pdf(folder / "cover_letter.pdf", [f"Alex Example\nDear {company},\nI would like to own your close."])
        (folder / "stories.json").write_text(json.dumps([]), encoding="utf-8")
        facts_mod.check(folder, PROFILE)
        if sent:
            (folder / "cv.tex.bak").write_bytes((folder / "cv.tex").read_bytes())  # the version before a revise
            (folder / "photo.jpg").write_bytes((PROFILE / "photo.jpg").read_bytes())
            copy = folder / "sent"
            copy.mkdir(exist_ok=True)
            digests = {}
            for name in ("cv.pdf", "cover_letter.pdf", "cv.tex", "cover_letter.tex", "photo.jpg"):
                (copy / name).write_bytes((folder / name).read_bytes())
                digests[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
            raw = json.loads((JOBS / "applications.json").read_text(encoding="utf-8"))
            raw[job_id]["materials"] = digests
            utils.write_json_atomic(JOBS / "applications.json", raw)


def make_other_ledgers() -> None:
    from door.core import utils

    utils.write_json_atomic(JOBS / "last_review.json", {"reviewed_at": at(6).isoformat(), "seen": ["jobindex.1001"]})
    freshness.record_scrape(JOBS, "jobindex", at(5))
    freshness.record_scrape(JOBS, "thehub", at(5))
    freshness.record_pushback(JOBS, "thehub", at(2))
    queue = candidates.load(JOBS)
    candidates.add(queue, "Queued Employer ApS", links=["https://example.com/careers"], titles=["Controller"], source="linkedin",
                   now=at(2), job_ids=["4000000001"])
    candidates.save(JOBS, queue)
    state = discovery_state.load(JOBS, "linkedin")
    discovery_state.record_run(state, at(2), mode="rotate", requests=20, pages=10, job_pages=2, outcome="ok", seconds=61.5)
    discovery_state.save(JOBS, "linkedin", state)
    utils.write_json_atomic(JOBS / "salary.json", {"jobindex.1002": {
        "low": 750000, "high": 900000, "currency": "DKK", "period": "year", "gross": True, "position": "mid",
        "basis": "ads for similar roles", "sources": ["https://example.com/salaries"], "ad_salary": None, "as_of": at(4).isoformat()}})
    (JOBS / "market").mkdir(parents=True, exist_ok=True)
    (JOBS / "market" / "report-2026-03-18.md").write_text("# Market report\n\nExcel appears in 12 of 15 ads.\n", encoding="utf-8")
    (JOBS / "drift" / "jobindex").mkdir(parents=True, exist_ok=True)
    (JOBS / "drift" / "jobindex" / "2026-03-15.html").write_text("<html><body>a page the scraper no longer fits</body></html>\n", encoding="utf-8")
    utils.write_json_atomic(JOBS / "skill_aliases.json", {"power bi": "Power BI", "powerbi": "Power BI", "teamwork": None})


def make_run_record() -> None:
    started = at(5, 6)
    record = {
        "started_at": started.isoformat(), "finished_at": (started + timedelta(minutes=4)).isoformat(), "elapsed_s": 240.0,
        "steps": ["search", "discover", "follow", "collect", "match"], "skipped": {},
        "search": {"sites": [{"site": "jobindex", "outcome": "ok", "count": 12}, {"site": "thehub", "outcome": "ok", "count": 3}],
                   "summary": "15 postings from 2 boards", "elapsed_s": 50.0},
        "discover": {"summary": "1 employer queued", "elapsed_s": 60.0},
        "follow": {"summary": "1 followed", "elapsed_s": 20.0},
        "collect": {"sites": [{"site": "greenhouse", "outcome": "ok", "count": 2}], "summary": "2 postings", "elapsed_s": 30.0},
        "match": {"scored": 14, "summary": "14 scored", "elapsed_s": 80.0},
        "new_above_threshold": ["jobindex.1001", "jobindex.1002"],
        "top": [{"id": "jobindex.1001", "score": 0.92, "title": "Financial Controller", "company": "Example Industries A/S"}],
        "failures": [],
    }
    find_cmd._write_run_record(record, JOBS, FIELDS["min_score"])


def main() -> None:
    make_profile()
    make_companies()
    make_postings()
    make_ledger()
    make_output()
    make_other_ledgers()
    make_run_record()


if __name__ == "__main__":
    main()
