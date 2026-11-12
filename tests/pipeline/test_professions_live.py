"""Live profession suite (#427, epic #426): each of the six Danish profiles searches Denmark's real boards.

Opt-in (marked `live` and `acceptance`; `./scripts/run-test.sh --live`; CI's weekly smoke run leaves it out). Per profession: `search` over every Danish board with the
profession's own keywords, then the count of on-topic postings (at least 5) and of employers queued (at least 1),
and a `follow` dry run whose resolved-feed count is printed as a number to watch, never asserted. A profession
whose board is missing today (`live_gap` in `tests/professions.py`) is a non-strict xfail naming the sub-issue.
The numbers printed (run with `-s`) are the baseline recorded in #426.
"""

import json
import shutil

import pytest

from door.commands import companies as companies_cmd
from door.core import candidates, careers_ai, workspace
from door.matching import title_fit
from door.pipeline import follow, search
from professions import PROFESSIONS
from profile_utils import write_config

# The real DNS readers: `tests/pipeline/conftest.py` stubs them for every test, a live follow dry run needs them.
_REAL_CNAME, _REAL_RESOLVES = companies_cmd._cname, companies_cmd._resolves

MIN_ON_TOPIC = 5

# A full search per profession (~25 min each): an acceptance run, left out of the weekly CI smoke run (#576).
pytestmark = pytest.mark.acceptance


def _params():
    for name, prof in PROFESSIONS.items():
        gap = prof.get("live_gap")
        marks = [pytest.mark.xfail(strict=False, reason=f"{gap[0]}: {gap[1]}")] if gap else []
        yield pytest.param(name, marks=marks)


def _follow_resolved(jobs_dir, profile_dir) -> str:
    """How many queued employers a `follow` dry run resolves to a feed (printed only); 'n/a' when the step fails."""
    try:
        block = follow._follow_core(dry_run=True, jobs_dir=jobs_dir, profile_dir=profile_dir)
    except Exception as exc:  # noqa: BLE001 - a number to watch, never a failure
        return f"n/a ({type(exc).__name__})"
    return f"{len(block.get('followed') or [])}/{block.get('checked', 0)}"


@pytest.mark.live
@pytest.mark.parametrize("name", _params())
def test_profession_search_live(name, tmp_path, monkeypatch, country_boards):
    prof = PROFESSIONS[name]
    config = prof["config"]
    profile_dir, jobs_dir = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile_dir, config)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(companies_cmd, "_cname", _REAL_CNAME)
    monkeypatch.setattr(companies_cmd, "_resolves", _REAL_RESOLVES)
    monkeypatch.setattr(careers_ai, "ask_careers_url", lambda *a, **k: None)  # no model call from a live run

    block = search._search_core(jobs_dir=jobs_dir, profile_dir=profile_dir)
    outcomes = {s["site"]: s["outcome"] for s in block["sites"]}
    if not any(o == "ok" for o in outcomes.values()):
        pytest.skip(f"every board resting or failing: {outcomes}")

    terms = title_fit.topic_terms(config)
    titles = [json.loads(p.read_text(encoding="utf-8")).get("title") or ""
              for p in sorted(jobs_dir.rglob("*.json")) if "postings" in p.parts]
    on_topic = sum(1 for t in titles if title_fit.on_topic(t, terms))
    queued = len(candidates.load(jobs_dir))
    resolved = _follow_resolved(jobs_dir, profile_dir)
    print(f"\nPROFESSION {name}: postings={block['postings']} on_topic={on_topic} queued={queued} "
          f"follow_resolved={resolved} boards={outcomes}")
    shutil.rmtree(jobs_dir, ignore_errors=True)

    assert on_topic >= MIN_ON_TOPIC, f"{name}: only {on_topic} on-topic postings of {len(titles)}; {outcomes}"
    assert queued >= 1, f"{name}: no employer queued"


@pytest.mark.live
@pytest.mark.skipif(shutil.which("claude") is None, reason="needs the claude CLI")
@pytest.mark.parametrize("name", list(PROFESSIONS))
def test_keywords_cover_the_on_topic_titles_live(name, tmp_path):
    """The words the `keywords` tool proposes for a profession's role targets keep its on-topic titles (opt-in; one Haiku call each)."""
    from door.commands import keywords as keywords_cmd

    prof = PROFESSIONS[name]
    profile_dir = tmp_path / "profile"
    write_config(profile_dir, prof["config"])
    result = keywords_cmd._keywords_core(prof["config"]["role_targets"], languages=["English", "Danish"],
                                         save=False, profile_dir=profile_dir)
    proposed = {**prof["config"], "search_keywords": result["keywords"], "topic_terms": result["topic_terms"]}
    terms = title_fit.topic_terms(proposed)
    missed = [t for t in prof["on_topic"] if not title_fit.on_topic(t, terms)]
    print(f"\nKEYWORDS {name}: {len(prof['on_topic']) - len(missed)}/{len(prof['on_topic'])} on-topic titles kept; missed={missed}")
    assert len(missed) * 2 <= len(prof["on_topic"]), f"{name}: proposed topic terms miss {missed}"


# The Danish universities as `companies add` follows them (#431): Oracle for DTU and SDU, Emply's embedded list for AU,
# HR-Manager for RUC and ITU. KU, CBS and AAU are reached through EURAXESS or not at all (see the issue).
UNIVERSITIES = [
    ("Technical University of Denmark", "oracle_hcm", "efzu.fa.em2.oraclecloud.com/CX_1"),
    ("University of Southern Denmark", "oracle_hcm", "fa-eosd-saasfaprod1.fa.ocs.oraclecloud.com/CX_1001"),
    ("Aarhus University", "emply", "https://international.au.dk/about/profile/vacant-positions/"),
    ("Roskilde University", "hr_manager", "ruc"),
    ("IT University of Copenhagen", "hr_manager", "ituniversitetet"),
]
MIN_UNIVERSITIES = 3


@pytest.mark.live
def test_researcher_finds_three_danish_universities_live(tmp_path, monkeypatch):
    """#431 acceptance: following the universities' feeds, `collect` writes on-topic postings of at least three of them."""
    from door.core import companies as store
    from door.pipeline import collect

    config = PROFESSIONS["researcher"]["config"]
    profile_dir, jobs_dir = tmp_path / "profile", tmp_path / "jobs"
    write_config(profile_dir, config)
    items = store.load(profile_dir)
    for name, platform, entry in UNIVERSITIES:
        store.record(items, name, feed=(platform, entry), status="followed", found_via="manual")
    store.save(profile_dir, items)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)

    block = collect._collect_core(jobs_dir=jobs_dir, profile_dir=profile_dir)

    terms = title_fit.topic_terms(config)
    found: dict[str, int] = {}
    for path in jobs_dir.rglob("*.json"):
        if "postings" not in path.parts:
            continue
        posting = json.loads(path.read_text(encoding="utf-8"))
        if title_fit.on_topic(posting.get("title") or "", terms):
            found[posting.get("company") or ""] = found.get(posting.get("company") or "", 0) + 1
    print(f"\nUNIVERSITIES on_topic_by_employer={found} sites={[(s['site'], s['outcome']) for s in block['sites']]}")
    shutil.rmtree(jobs_dir, ignore_errors=True)

    assert len(found) >= MIN_UNIVERSITIES, f"only {sorted(found)} had on-topic postings; {block['summary']}"
