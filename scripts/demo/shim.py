"""Run the real `door` CLI against a demo sandbox, with the network and `claude` stubbed.

`record.sh` puts a `door` wrapper in the sandbox that runs this file. Everything the
user sees is the real command and its real output; only the three things that would
reach outside are replaced:

- each job board in `postings.POSTINGS` is a fake scraper module that reports a few
  keyword searches and returns the made-up ads, and those are the boards searched,
- `follow` finds each employer's feed in `postings.FEEDS` instead of reading the web, and
  `collect` reads those feeds from a fake Greenhouse module,
- scoring hands back each ad's canned score instead of calling `claude -p`,
- tailoring writes a ready-made CV and cover letter (real PDFs, made with pypdfium2)
  instead of running the tailor agent.

`DOOR_DEMO_DIR` is the sandbox: its `profile/` and `jobs/` replace the repo's, so a
recording never shows (or touches) your own data.
"""

import os
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import postings as demo_data  # noqa: E402

from door.commands import _common as common  # noqa: E402
from door.commands import companies as companies_cmd  # noqa: E402
from door.commands import prepare as prepare_cmd  # noqa: E402
from door.commands import salary as salary_cmd  # noqa: E402
from door.core import discovery_sources, drive, lock, sites, workspace  # noqa: E402
from door.core.models import JobPosting, make_job_id  # noqa: E402
from door.matching import scorer  # noqa: E402
from door.tailoring import readability  # noqa: E402
from door.scrapers import report  # noqa: E402

# Pauses that make the live output readable at recording speed.
SEARCH_PAUSE_S = 1.0
FOLLOW_PAUSE_S = 0.8
FEED_PAUSE_S = 0.8
SCORE_PAUSE_S = 0.35
TAILOR_S = 7.0


def _fake_scraper(site: str) -> types.ModuleType:
    def scrape(config: dict, known_ids=frozenset(), **kwargs) -> list[dict]:
        for keyword, hits in demo_data.KEYWORD_HITS[site]:
            time.sleep(SEARCH_PAUSE_S)
            report(f"'{keyword}': {hits} results", site=site)
        now = datetime.now(timezone.utc)
        records = []
        for i, ad in enumerate(demo_data.POSTINGS[site]):
            platform_id = f"{site}-{i}"
            records.append(JobPosting(
                id=make_job_id(site, platform_id),
                title=ad["title"],
                company=ad["company"],
                location="Copenhagen",
                url=f"https://example.com/{site}/{platform_id}",
                description=ad["text"].format(title=ad["title"]),
                source=site,
                scraped_at=now,
                platform_id=platform_id,
                posted_at=now - timedelta(hours=3 + i),
                apply_type="external",
            ).model_dump(mode="json"))
        return records

    module = types.ModuleType(sites.SITES[site].module)
    module.scrape = scrape
    return module


def _posting(source: str, company: str, ad: dict, platform_id: str, age_h: int) -> dict:
    now = datetime.now(timezone.utc)
    return JobPosting(
        id=make_job_id(source, platform_id),
        title=ad["title"],
        company=company,
        location="Copenhagen",
        url=f"https://example.com/{source}/{platform_id}",
        description=ad["text"].format(title=ad["title"]),
        source=source,
        scraped_at=now,
        platform_id=platform_id,
        posted_at=now - timedelta(hours=age_h),
        apply_type="external",
    ).model_dump(mode="json")


def _fake_classify(session, company: dict, known: set, ctx):
    """`follow`'s detection: the feed `postings.FEEDS` names, or nothing found."""
    time.sleep(FOLLOW_PAUSE_S)
    feed = demo_data.FEEDS.get(company["company"])
    if feed is None:
        return None
    platform, entry, _ = feed
    return "suggestions", {"platform": platform, "entry": entry, "config_key": "greenhouse_boards",
                           "evidence": f"https://job-boards.greenhouse.io/{entry} is a Greenhouse board"}


def _fake_greenhouse() -> types.ModuleType:
    by_entry = {entry: (company, ads) for company, (_, entry, ads) in demo_data.FEEDS.items()}

    def scrape(config: dict, known_ids=frozenset(), **kwargs) -> list[dict]:
        records = []
        for entry in config.get("greenhouse_boards", []):
            time.sleep(FEED_PAUSE_S)
            company, ads = by_entry[entry]
            report(f"{entry}: {len(ads)} jobs", site="greenhouse")
            records += [_posting("greenhouse", company, ad, f"{entry}-{i}", 2 + i) for i, ad in enumerate(ads)]
        return records

    module = types.ModuleType("door.scrapers.feeds.greenhouse")
    module.scrape = scrape
    return module


def _canned_scores() -> dict[str, dict]:
    canned = {ad["title"] + "|" + ad["company"]: ad
              for ads in demo_data.POSTINGS.values() for ad in ads}
    for company, (_, _, ads) in demo_data.FEEDS.items():
        for ad in ads:
            canned.setdefault(ad["title"] + "|" + company, ad)
    return canned


def _fake_score_postings(postings, *, on_result=None, **kwargs):
    canned = _canned_scores()
    results = {}
    for posting in postings:
        time.sleep(SCORE_PAUSE_S)
        ad = canned.get(posting["title"] + "|" + posting["company"], {})
        result = {
            "score": ad.get("score") or 0.3,
            "score_reason": ad.get("reason", "Little overlap with the CV."),
            "matching_skills": ad.get("matching", []),
            "missing_skills": ad.get("missing", []),
            "scored_by": scorer.DEFAULT_MODEL,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }
        results[posting["id"]] = result
        if on_result is not None:
            on_result(posting["id"], result)
    return results, []


_CV_TEX = r"""% Keywords: budgeting and forecasting, team leadership, IFRS, Power BI, stakeholder communication
% Tailoring: led with building the Acme Corp controlling function; kept the IFRS 15 thesis; condensed the Example Retail role to one line
\documentclass{article}
\begin{document}
Jane Doe -- Senior Financial Controller
\end{document}
"""

_LETTER_TEX = r"""\documentclass{letter}
\begin{document}
Dear hiring team,

%s
\end{document}
"""

_LETTER_BODY = (
    "I built the group controlling function at Acme Corp from nothing: setting the "
    "reporting calendar, halving the month-end close and partnering with sales and "
    "operations on the budgets the company plans with today. Your Head of Finance role asks "
    "for exactly that, at a company growing as fast as Globex Energy. "
) * 6


def _pdf(path: Path, pages: list[str]) -> None:
    """One A4 page per string, its paragraphs wrapped at about 80 characters, in 11 pt Helvetica."""
    import ctypes
    import textwrap

    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    doc = pdfium.PdfDocument.new()
    font = raw.FPDFText_LoadStandardFont(doc, b"Helvetica")
    for text in pages:
        page = doc.new_page(595, 842)
        lines = [line for para in text.split("\n") for line in (textwrap.wrap(para, 80) or [""])]
        for i, line in enumerate(lines):
            obj = raw.FPDFPageObj_CreateTextObj(doc, font, ctypes.c_float(11))
            buf = ctypes.create_string_buffer((line + "\0").encode("utf-16-le"))
            raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
            raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 72, 842 - 84 - i * 15)
            raw.FPDFPage_InsertObject(page.raw, obj)
        raw.FPDFPage_GenerateContent(page.raw)
    doc.save(str(path))


def _fake_run_tailor(job_id: str, posting_path: Path, timeout_s=None) -> bool:
    time.sleep(TAILOR_S)
    out = workspace.JOBS_DIR / "output" / job_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "posting.json").write_text(posting_path.read_text())
    (out / "cv.tex").write_text(_CV_TEX)
    (out / "cover_letter.tex").write_text(_LETTER_TEX % _LETTER_BODY)
    _pdf(out / "cv.pdf", ["Jane Doe\nSenior Financial Controller\n\n" + _LETTER_BODY, _LETTER_BODY])
    _pdf(out / "cover_letter.pdf", ["Dear hiring team,\n\n" + _LETTER_BODY])
    return True


def install(sandbox: Path) -> None:
    workspace.PROFILE_DIR = sandbox / "profile"
    workspace.JOBS_DIR = sandbox / "jobs"
    workspace.BACKUPS_DIR = sandbox / "backups"
    workspace.UPSKILL_DIR = sandbox / "upskill"
    # Never your Google Drive: the sync would treat the sandbox as the workspace and push it
    # over your archive (or pull yours in). A config dir of its own is a computer never connected.
    drive._BASE = sandbox / "config"
    lock.pre_acquire_hook = lambda purpose, jobs_dir: None
    lock.post_release_hook = lambda purpose, jobs_dir: None
    for site in demo_data.POSTINGS:
        sys.modules[sites.SITES[site].module] = _fake_scraper(site)
    sites.boards_for_location = lambda location: list(demo_data.POSTINGS)
    # no discovery source: the demo has no network, and its discover line names none ("no discovery source")
    discovery_sources.SOURCES.clear()
    sys.modules["door.scrapers.feeds.greenhouse"] = _fake_greenhouse()
    companies_cmd._session = lambda: None
    companies_cmd._classify = _fake_classify
    scorer.score_postings = _fake_score_postings
    prepare_cmd._run_tailor = _fake_run_tailor
    prepare_cmd._HEARTBEAT_INTERVAL_S = 2.0
    # no web search for a salary: none found, so prepare says nothing about it
    salary_cmd._salary_core = lambda job_id, **kwargs: {"job_id": job_id, "found": False}
    # the stand-in PDFs hold a summary, not the tailored .tex: an ATS reading them back would miss it all
    readability.check_pdf = lambda *args, **kwargs: []
    common._claude_available = lambda: True


if __name__ == "__main__":
    install(Path(os.environ["DOOR_DEMO_DIR"]))
    from door.cli import cli

    cli(prog_name="door")
