"""`companies` (list, add, remove, why) and the detection behind them (issue #233).

HTTP is mocked with `responses`; DNS goes through `companies._cname`, patched.
"""

import json
import re

import pytest
import responses
from click.testing import CliRunner

from door.cli import cli
from door.commands import companies as companies_cmd
from door.core import companies as companies_store
from profile_utils import write_config
from cli_utils import result_text
from paths import TESTS_DIR
from urllib.parse import urlparse


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(companies_cmd, "_cname", lambda host: None)
    monkeypatch.setattr(companies_cmd, "_resolves", lambda host: False)


def _no_board(*hosts):
    for pattern in hosts:
        responses.add(responses.GET, re.compile(pattern), status=404)


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #

@responses.activate
def test_a_name_is_probed_greenhouse_then_lever_us_then_lever_eu(cli_env):
    _no_board(r"https://boards-api\.greenhouse\.io/.*")
    responses.add(responses.GET, re.compile(r"https://api\.lever\.co/v0/postings/siteimprove.*"), status=404)
    responses.add(responses.GET, re.compile(r"https://api\.eu\.lever\.co/v0/postings/siteimprove.*"),
                  json=[{"id": "1", "text": "Engineer"}])

    result = companies_cmd._resolve_core(["Siteimprove"])

    [found] = result["results"]
    assert (found["platform"], found["entry"], found["config_key"]) == ("lever", "siteimprove", "lever_companies")
    assert "EU" in found["evidence"]
    urls = [c.request.url for c in responses.calls if "robots" not in c.request.url]
    assert urls[0].startswith("https://boards-api.greenhouse.io/v1/boards/siteimprove/jobs")
    assert urls[-1].startswith("https://api.eu.lever.co/v0/postings/siteimprove")


def test_career_hosts_are_guessed_in_the_profiles_country():
    """`careers.<slug>.com` anywhere; in a country with a file also its own domain, with the career
    words of its languages (`karriere` in Denmark)."""
    assert companies_cmd._host_guesses("") == ("careers.{s}.com", "jobs.{s}.com")
    dk = companies_cmd._host_guesses("Copenhagen")
    assert dk[:2] == ("careers.{s}.com", "jobs.{s}.com")
    assert {"careers.{s}.dk", "jobs.{s}.dk", "job.{s}.dk", "karriere.{s}.dk"} <= set(dk)
    assert not any(h.endswith(".hu") for h in dk)


def test_career_hosts_follow_a_new_countrys_data(monkeypatch):
    from door import i18n

    hu = i18n.CountryPack(code="hu", name="Hungary", languages=["hu"], cities={"budapest": []})
    lang = i18n.LanguagePack(code="hu", name="Hungarian", career_site_words=["karrier", "állás", "nyitott pozíciók"])
    monkeypatch.setattr(i18n, "countries", lambda: {"hu": hu})
    monkeypatch.setattr(i18n, "languages", lambda: {"en": i18n.load_language_file(i18n.LANG_DIR / "en.toml"), "hu": lang})
    guesses = companies_cmd._host_guesses("Budapest")
    assert {"careers.{s}.hu", "karrier.{s}.hu", "allas.{s}.hu"} <= set(guesses)
    assert not any(" " in h or h.endswith(".dk") for h in guesses)


def test_career_hosts_of_denmark_and_hungary_keep_what_they_were():
    dk = set(companies_cmd._host_guesses("Copenhagen"))
    assert dk == {"careers.{s}.com", "jobs.{s}.com", "careers.{s}.dk", "jobs.{s}.dk", "karriere.{s}.dk", "job.{s}.dk",
                  "stillinger.{s}.dk", "karrieremuligheder.{s}.dk"}
    hu = set(companies_cmd._host_guesses("Budapest"))
    assert {"careers.{s}.hu", "jobs.{s}.hu", "karrier.{s}.hu", "allas.{s}.hu"} <= hu


def test_career_hosts_read_the_countrys_tld_and_host_labels(monkeypatch):
    from door import i18n

    gb = i18n.CountryPack(code="gb", name="United Kingdom", tlds=["uk"], career_hosts=["recruit"], cities={"london": []})
    monkeypatch.setattr(i18n, "countries", lambda: {"gb": gb})
    guesses = companies_cmd._host_guesses("London")
    assert "recruit.{s}.uk" in guesses and "careers.{s}.uk" in guesses
    assert not any(h.endswith(".gb") for h in guesses)


def test_career_hosts_without_tlds_use_the_country_code(monkeypatch):
    from door import i18n

    zz = i18n.CountryPack(code="zz", name="Zedland", career_hosts=["recruit"])
    monkeypatch.setattr(i18n, "countries", lambda: {"zz": zz})
    assert "recruit.{s}.zz" in companies_cmd._host_guesses("Zedland")


@responses.activate
def test_a_name_is_tried_on_the_career_host_of_the_profiles_country(cli_env, monkeypatch):
    _no_board(r"https://.*")
    monkeypatch.setattr(companies_cmd, "_cname",
                        lambda host: "acme.wd3.myworkdayjobs.com" if host == "karriere.acme.dk" else None)

    [found] = companies_cmd._resolve_core(["Acme"], location="Copenhagen")["results"]
    assert found["platform"] == "career_sites"

    [missed] = companies_cmd._resolve_core(["Acme"])["results"]
    assert missed["platform"] is None


@responses.activate
def test_an_empty_board_is_not_a_match(cli_env):
    responses.add(responses.GET, re.compile(r"https://boards-api\.greenhouse\.io/.*"), json={"jobs": []})
    _no_board(r"https://api(\.eu)?\.lever\.co/.*", r"https://api\.ashbyhq\.com/.*", r"https://.*\.recruitee\.com/.*",
              r"https://.*\.teamtailor\.com/.*", r"https://apply\.workable\.com/.*")

    [found] = companies_cmd._resolve_core(["Nowhere ApS"])["results"]


    assert found["platform"] is None and found["entry"] is None
    assert found["candidates"] == ["nowhere"]


@responses.activate
def test_a_careers_url_is_read_without_probing(cli_env):
    [found] = companies_cmd._resolve_core(["https://job-boards.greenhouse.io/trustpilot"])["results"]

    assert (found["platform"], found["entry"]) == ("greenhouse", "trustpilot")
    assert len(responses.calls) == 0


@responses.activate
def test_a_jobylon_ad_link_is_followed_to_its_company(cli_env):
    """Jobbsafari and Platsbanken apply links name an ad; the ad page names the company (#528)."""
    ad = (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "jobylon" / "job_393911.html").read_text(encoding="utf-8")
    responses.add(responses.GET, "https://emp.jobylon.com/jobs/393911/", body=ad, content_type="text/html; charset=utf-8")

    [found] = companies_cmd._resolve_core(["https://emp.jobylon.com/jobs/393911-lyko-butikschef-till-lyko-marieberg/"])["results"]

    assert (found["platform"], found["entry"], found["config_key"]) == ("jobylon", "2420", "jobylon_companies")
    assert "393911" in found["evidence"]


@responses.activate
def test_a_jobylon_ad_that_is_gone_is_unfollowable_for_now(cli_env):
    responses.add(responses.GET, "https://emp.jobylon.com/jobs/393911/", status=404)

    [found] = companies_cmd._resolve_core(["https://emp.jobylon.com/jobs/393911-lyko-butikschef/"])["results"]

    assert found["platform"] == "jobylon" and found["entry"] is None and found["refusal"] == "cant_yet"


@responses.activate
def test_a_career_host_is_recognised_by_its_cname(cli_env, monkeypatch):
    monkeypatch.setattr(companies_cmd, "_cname", lambda host: "secure.recruitee.com" if host == "careers.trackman.com" else None)

    [found] = companies_cmd._resolve_core(["careers.trackman.com"])["results"]

    assert (found["platform"], found["entry"]) == ("recruitee", "careers.trackman.com")
    assert len(responses.calls) == 0


@responses.activate
def test_a_name_is_tried_as_a_career_host_on_rmk(cli_env, monkeypatch):
    """Novo Nordisk is found through careers.novonordisk.com's CNAME to jobs2web."""
    _no_board(r"https://boards-api\.greenhouse\.io/.*", r"https://api(\.eu)?\.lever\.co/.*", r"https://api\.ashbyhq\.com/.*",
              r"https://.*\.recruitee\.com/.*", r"https://.*\.teamtailor\.com/.*", r"https://apply\.workable\.com/.*")
    monkeypatch.setattr(companies_cmd, "_cname",
                        lambda host: "novonordisk.jobs2web.com" if host == "careers.novonordisk.com" else None)

    [found] = companies_cmd._resolve_core(["Novo Nordisk A/S"])["results"]

    assert (found["platform"], found["entry"]) == ("successfactors", "careers.novonordisk.com")


@responses.activate
def test_a_name_is_tried_on_its_likely_career_hosts_pages(cli_env, monkeypatch):
    """careers.novonordisk.com has no CNAME (an A record); its page shows SAP RMK."""
    _no_board(r"https://boards-api\.greenhouse\.io/.*", r"https://api(\.eu)?\.lever\.co/.*", r"https://api\.ashbyhq\.com/.*",
              r"https://.*\.recruitee\.com/.*", r"https://.*\.teamtailor\.com/.*", r"https://apply\.workable\.com/.*")
    monkeypatch.setattr(companies_cmd, "_resolves", lambda host: host == "careers.novonordisk.com")
    responses.add(responses.GET, "https://careers.novonordisk.com/",
                  body='<script src="https://rmkcdn.successfactors.com/8c/js/app.js"></script>')

    [found] = companies_cmd._resolve_core(["Novo Nordisk"])["results"]

    assert (found["platform"], found["entry"]) == ("successfactors", "careers.novonordisk.com")


@responses.activate
def test_a_custom_recruitee_host_is_confirmed_by_its_feed(cli_env):
    responses.add(responses.GET, "https://careers.trackman.com/", body='{"assetHost":"https://x.recruiteecdn.com"}')
    responses.add(responses.GET, "https://careers.trackman.com/api/offers/", json={"offers": [{"id": 1}]})

    [found] = companies_cmd._resolve_core(["careers.trackman.com"])["results"]

    assert (found["platform"], found["entry"]) == ("recruitee", "careers.trackman.com")
    assert "lists open jobs" in found["evidence"]


@responses.activate
def test_a_signature_whose_feed_is_empty_is_not_a_match(cli_env):
    responses.add(responses.GET, "https://careers.acme.dk/", body='{"assetHost":"https://x.recruiteecdn.com"}')
    responses.add(responses.GET, "https://careers.acme.dk/api/offers/", status=404)

    [found] = companies_cmd._resolve_core(["careers.acme.dk"])["results"]

    assert found["entry"] is None


@responses.activate
def test_a_careers_page_is_read_for_an_embedded_board(cli_env):
    responses.add(responses.GET, "https://careers.acme.dk/",
                  body='<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>')

    [found] = companies_cmd._resolve_core(["https://careers.acme.dk/"])["results"]

    assert (found["platform"], found["entry"]) == ("greenhouse", "acme")


def test_without_probing_a_name_resolves_to_nothing(cli_env):
    [found] = companies_cmd._resolve_core(["Trustpilot"], probe=False)["results"]
    assert found["platform"] is None and found["candidates"] == ["trustpilot"]


def test_a_workday_link_becomes_a_career_site(cli_env):
    [found] = companies_cmd._resolve_core(["https://velux.wd3.myworkdayjobs.com/Velux"])["results"]
    assert (found["platform"], found["entry"]) == ("career_sites", "https://velux.wd3.myworkdayjobs.com")
    assert "Workday" in found["evidence"]


_ORACLE_SITES = re.compile(r"https://efzu\.fa\.em2\.oraclecloud\.com/hcmRestApi/resources/latest/recruitingCESites.*")
_ORACLE_SITE_LIST = {"items": [{"SiteNumber": "CX_1", "StatusCode": "ORA_INACTIVE"},
                               {"SiteNumber": "CX_1001", "StatusCode": "ORA_ACTIVE"}]}


@responses.activate
def test_an_oracle_link_is_followed_on_its_host_and_site(cli_env):
    responses.add(responses.GET, _ORACLE_SITES, json={"items": [{"SiteNumber": "CX_1001", "StatusCode": "ORA_ACTIVE"}]})
    [found] = companies_cmd._resolve_core(["https://efzu.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001"])["results"]
    assert (found["platform"], found["entry"], found["config_key"]) == (
        "oracle_hcm", "efzu.fa.em2.oraclecloud.com/CX_1001", "oracle_hcm_companies")


@responses.activate
def test_an_oracle_link_into_an_inactive_site_is_followed_on_the_active_one(cli_env):
    responses.add(responses.GET, _ORACLE_SITES, json=_ORACLE_SITE_LIST)
    [found] = companies_cmd._resolve_core(["https://efzu.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/8384"])["results"]
    assert found["entry"] == "efzu.fa.em2.oraclecloud.com/CX_1001" and "CX_1" in found["evidence"]


def test_an_oracle_link_without_a_site_cannot_be_followed_yet(cli_env):
    [found] = companies_cmd._resolve_core(["https://efzu.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/"], probe=False)["results"]
    assert found["platform"] == "oracle_hcm" and found["entry"] is None and found["refusal"] == "cant_yet"


_PHENOM = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "phenom"
_WD = "https://acmepharma.wd3.myworkdayjobs.com"


def _phenom_front_end(monkeypatch, jobs_total):
    """careers.acmepharma.example: a CNAME for Phenom's, its Workday site listing *jobs_total* jobs publicly."""
    monkeypatch.setattr(companies_cmd, "_cname", lambda host: "acmepharma.phenompeople.net")
    host = "https://careers.acmepharma.example"
    responses.add(responses.GET, f"{host}/", status=302, headers={"Location": f"{host}/global/en/home"})
    responses.add(responses.GET, f"{host}/global/en/home", body=(_PHENOM / "home.html").read_text())
    responses.add(responses.GET, f"{host}/global/en/search-results", body=(_PHENOM / "search_results.html").read_text())
    responses.add(responses.POST, f"{_WD}/wday/cxs/acmepharma/Acme_Careers_Site/jobs",
                  json={"total": jobs_total, "jobPostings": []})
    responses.add(responses.GET, f"{_WD}/Acme_Careers_Site/siteMap.xml", body="<urlset></urlset>")


@responses.activate
def test_a_phenom_front_end_is_followed_on_the_workday_site_behind_it(cli_env, monkeypatch):
    _phenom_front_end(monkeypatch, jobs_total=40)
    [found] = companies_cmd._resolve_core(["careers.acmepharma.example"])["results"]
    assert (found["platform"], found["entry"], found["config_key"]) == ("career_sites", f"{_WD}/Acme_Careers_Site", "career_sites")
    assert "phenompeople" in found["evidence"] and found["refusal"] is None


@responses.activate
def test_a_phenom_front_end_whose_workday_list_is_empty_cannot_be_followed_yet(cli_env, monkeypatch):
    _phenom_front_end(monkeypatch, jobs_total=0)
    result = companies_cmd._add_core(["careers.acmepharma.example"], probe=True, profile_dir=cli_env.profile_dir)
    [item] = result["results"]
    assert item["status"] == "unfollowable" and item["platform"] == "phenom" and item["refusal"] == "cant_yet"
    assert "lists no jobs publicly" in item["reason"]
    [company] = _list(cli_env.profile_dir)
    assert company.refusal == "cant_yet" and company.feed is None


# --------------------------------------------------------------------------- #
# add / list / remove / why (profile/companies.json)
# --------------------------------------------------------------------------- #

def _list(profile_dir):
    return companies_store.load(profile_dir)


def test_add_records_a_followed_employer_with_its_feed_and_evidence(cli_env):
    result = companies_cmd._add_core(["https://job-boards.greenhouse.io/trustpilot"], probe=False,
                                     profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)

    [item] = result["results"]
    assert (item["status"], item["platform"], item["entry"], item["new"]) == ("followed", "greenhouse", "trustpilot", True)
    [company] = _list(cli_env.profile_dir)
    assert (company.name, company.status, company.found_via) == ("Trustpilot", "followed", "manual")
    assert company.feed.platform == "greenhouse" and "Greenhouse board link" in company.evidence
    assert company.first_seen and company.last_checked


def test_add_never_touches_the_config(cli_env):
    write_config(cli_env.profile_dir, {"role_targets": ["data"], "location": "Copenhagen", "min_score": 0.6})
    before = (cli_env.profile_dir / "config.json").read_text()

    companies_cmd._add_core(["https://job-boards.greenhouse.io/trustpilot"], probe=False, profile_dir=cli_env.profile_dir)

    assert (cli_env.profile_dir / "config.json").read_text() == before


def test_a_followed_platform_needs_no_listing_anywhere(cli_env):
    companies_cmd._add_core(["https://jobs.ashbyhq.com/pleo", "https://apply.workable.com/dreamdata/"], probe=False,
                            profile_dir=cli_env.profile_dir)

    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    assert "ashby" not in json.dumps(config) and "workable_companies" not in config
    assert companies_store.feed_entries(cli_env.profile_dir, "ashby") == ["pleo"]
    assert companies_store.feed_entries(cli_env.profile_dir, "workable") == ["dreamdata"]


def test_add_twice_is_one_employer(cli_env):
    for _ in range(2):
        result = companies_cmd._add_core(["https://job-boards.greenhouse.io/trustpilot"], probe=False,
                                         profile_dir=cli_env.profile_dir)
    assert len(_list(cli_env.profile_dir)) == 1 and result["results"][0]["new"] is False


def test_add_records_unfollowable_and_unresolved_employers_with_the_reason(cli_env):
    result = companies_cmd._add_core(["https://bankinvest.hr-on.com/show-job/357305", "Nobody ApS"],
                                     probe=False, profile_dir=cli_env.profile_dir)

    hr_on, nobody = _list(cli_env.profile_dir)
    assert (hr_on.status, hr_on.feed) == ("unfollowable", None) and "robots.txt" in hr_on.reason
    assert (nobody.name, nobody.status) == ("Nobody ApS", "unresolved") and "nobody" in nobody.reason
    assert [r["status"] for r in result["results"]] == ["unfollowable", "unresolved"]
    assert companies_store.feed_config(cli_env.profile_dir) == {}


def test_add_follows_an_oracle_site_and_the_scraper_reads_it_from_the_list(cli_env):
    companies_cmd._add_core(["https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1001"], probe=False,
                            profile_dir=cli_env.profile_dir)
    [bank] = _list(cli_env.profile_dir)
    assert (bank.status, bank.feed.platform, bank.feed.id) == ("followed", "oracle_hcm", "ejqi.fa.ocs.oraclecloud.eu/CX_1001")
    assert companies_store.feed_config(cli_env.profile_dir) == {"oracle_hcm_companies": ["ejqi.fa.ocs.oraclecloud.eu/CX_1001"]}
    assert companies_store.feed_names([bank]) == {"oracle_hcm_companies": {"ejqi.fa.ocs.oraclecloud.eu/cx_1001": bank.name}}


def test_add_records_why_a_platform_is_not_followed(cli_env):
    """#438: HR-ON is a refusal ("must not"), told apart from the reason text; list and why show it."""
    result = companies_cmd._add_core(["https://bankinvest.hr-on.com/show-job/357305"], probe=False,
                                     profile_dir=cli_env.profile_dir)
    [dalux] = _list(cli_env.profile_dir)
    assert dalux.refusal == "must_not" and result["results"][0]["refusal"] == "must_not"
    row = companies_cmd._list_core(profile_dir=cli_env.profile_dir)["companies"][0]
    assert row["refusal"] == "must_not"
    assert "won't follow" in companies_cmd._company_line(row)
    assert companies_cmd._company_line({**row, "refusal": "cant_yet"}).count("can't yet") == 1


def test_add_dry_run_writes_nothing(cli_env):
    before = (cli_env.profile_dir / "config.json").read_text()

    result = companies_cmd._add_core(["https://job-boards.greenhouse.io/trustpilot"], dry_run=True, probe=False,
                                     profile_dir=cli_env.profile_dir)

    assert result["dry_run"] and result["results"][0]["status"] == "followed"
    assert not (cli_env.profile_dir / "companies.json").exists()
    assert (cli_env.profile_dir / "config.json").read_text() == before


def test_a_miss_never_unfollows_an_employer(cli_env):
    companies_cmd._add_core(["https://job-boards.greenhouse.io/trustpilot"], probe=False, profile_dir=cli_env.profile_dir)
    companies_cmd._add_core(["Trustpilot"], probe=False, profile_dir=cli_env.profile_dir)
    [company] = _list(cli_env.profile_dir)
    assert company.status == "followed" and company.feed.id == "trustpilot"


def test_add_waits_for_a_run_in_progress(cli_env):
    from door.core import lock

    with lock.ledger_lock(cli_env.jobs_dir, "run"):
        # another process would be refused; here the same thread re-enters, so check the decorator is applied
        assert companies_cmd._add_core.__wrapped__ is not None
        assert companies_cmd._remove_core.__wrapped__ is not None


def _follow(cli_env, *names):
    for name in names:
        companies_cmd._add_core([f"https://job-boards.greenhouse.io/{name.lower().replace(' ', '')}"], probe=False,
                                profile_dir=cli_env.profile_dir)


def test_remove_unfollows_by_name_ignoring_case_and_suffix(cli_env):
    _follow(cli_env, "Trustpilot", "Acme")

    result = companies_cmd._remove_core(["trustpilot A/S", "Ghost"], profile_dir=cli_env.profile_dir)

    assert [r["name"] for r in result["removed"]] == ["Trustpilot"] and result["not_found"] == ["Ghost"]
    assert [c.name for c in _list(cli_env.profile_dir)] == ["Acme"]
    assert companies_store.feed_entries(cli_env.profile_dir, "greenhouse") == ["acme"]


def test_list_filters_by_status_and_found_via(cli_env):
    _follow(cli_env, "Trustpilot")
    companies_cmd._add_core(["Nobody"], probe=False, profile_dir=cli_env.profile_dir)

    everything = companies_cmd._list_core(profile_dir=cli_env.profile_dir)
    assert [c["name"] for c in everything["companies"]] == ["Trustpilot", "Nobody"]
    assert everything["counts"] == {"followed": 1, "unfollowable": 0, "unresolved": 1, "dormant": 0}
    assert [c["name"] for c in companies_cmd._list_core(status="unresolved", profile_dir=cli_env.profile_dir)["companies"]] == ["Nobody"]
    assert companies_cmd._list_core(found_via="linkedin", profile_dir=cli_env.profile_dir)["companies"] == []
    with pytest.raises(ValueError):
        companies_cmd._list_core(status="nope", profile_dir=cli_env.profile_dir)


def test_why_counts_the_postings_that_came_from_the_employer(cli_env):
    _follow(cli_env, "Trustpilot")
    _posting(cli_env.jobs_dir, "jobindex", "Trustpilot ApS", x=1)
    _posting(cli_env.jobs_dir, "greenhouse", "Trustpilot", x=2)
    _posting(cli_env.jobs_dir, "greenhouse", "Trustpilot", x=3, y=3)
    _posting(cli_env.jobs_dir, "jobindex", "Someone Else")

    result = companies_cmd._why_core("trustpilot", profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)

    assert result["postings"] == 3 and result["by_source"] == {"greenhouse": 2, "jobindex": 1}
    assert result["company"]["feed"] == {"platform": "greenhouse", "id": "trustpilot"}
    with pytest.raises(LookupError):
        companies_cmd._why_core("Ghost", profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)


# --------------------------------------------------------------------------- #
# the detection over the companies in postings (what `follow` does for the queued employers)
# --------------------------------------------------------------------------- #

def _suggest_core(*, add=False, probe=False, profile_dir, jobs_dir):
    """Queue the companies of every posting in jobs/ as `search` does, run `follow`'s detection over
    them (recording only with ``add``), and give the answer as lists of what was found."""
    from datetime import datetime, timezone
    from pathlib import Path

    from door.pipeline import follow as follow_step
    from door.pipeline import search as search_step

    search_step.queue_postings(sorted((Path(jobs_dir) / "postings").glob("*/*/*.json")), jobs_dir, profile_dir, datetime.now(timezone.utc))
    block = follow_step._follow_core(dry_run=not add, probe=probe, jobs_dir=jobs_dir, profile_dir=profile_dir)
    rows = block["results"]
    followed = [r for r in rows if r["status"] == "followed"]
    return {
        "suggestions": sorted(followed, key=lambda r: (-r["postings"], r["company"].lower())),
        "unfollowable": [r for r in rows if r["status"] == "unfollowable"],
        "unresolved": [r for r in rows if r["status"] == "unresolved" and r["external"]],
        "added": followed if add else [],
    }


def _posting(jobs_dir, site, company, **fields):
    path = jobs_dir / "postings" / "2026-10-10" / site / f"{site}.{company.lower().replace(' ', '-')}.{len(fields)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": path.stem, "company": company, "title": "Data Scientist", "source": site, **fields}))


def test_suggest_lists_the_companies_seen_in_postings_that_a_feed_can_follow(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Trustpilot", apply_url="https://job-boards.greenhouse.io/trustpilot/jobs/1")
    _posting(cli_env.jobs_dir, "jobindex", "Trustpilot", url="https://job-boards.greenhouse.io/trustpilot/jobs/2", title="Data Engineer")
    _posting(cli_env.jobs_dir, "thehub", "Pleo", apply_url="https://jobs.ashbyhq.com/pleo/abc")
    _posting(cli_env.jobs_dir, "jobindex", "Danske Bank", apply_url="https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/x")
    _posting(cli_env.jobs_dir, "jobindex", "Acme", apply_url="https://acme.dk/jobs/1")
    _posting(cli_env.jobs_dir, "jobindex", "Hosted", url="https://www.jobindex.dk/jobannonce/h1/")
    write_config(cli_env.profile_dir, {"role_targets": ["data"], "location": "x"})
    companies_cmd._add_core(["https://jobs.ashbyhq.com/pleo"], probe=False, profile_dir=cli_env.profile_dir)

    result = _suggest_core(profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)

    assert [(s["company"], s["entry"], s["postings"]) for s in result["suggestions"]] == [("Trustpilot", "trustpilot", 2)]
    assert [u["company"] for u in result["unfollowable"]] == ["Danske Bank"]
    assert [u["company"] for u in result["unresolved"]] == ["Acme"]


def test_suggest_add_records_them_all_in_the_employer_list(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Trustpilot", apply_url="https://job-boards.greenhouse.io/trustpilot/jobs/1")
    _posting(cli_env.jobs_dir, "jobindex", "Danske Bank", apply_url="https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/x")
    _posting(cli_env.jobs_dir, "thehub", "Acme", apply_url="https://acme.dk/jobs/1")

    result = _suggest_core(add=True, profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)

    assert [(a["company"], a["platform"], a["entry"], a["config_key"]) for a in result["added"]] == [
        ("Trustpilot", "greenhouse", "trustpilot", "greenhouse_boards")]
    by_name = {c.name: c for c in _list(cli_env.profile_dir)}
    assert by_name["Trustpilot"].status == "followed" and by_name["Trustpilot"].found_via == "jobindex"
    assert by_name["Danske Bank"].status == "unfollowable" and by_name["Danske Bank"].refusal == "cant_yet"
    assert (by_name["Acme"].status, by_name["Acme"].found_via) == ("unresolved", "thehub")


def test_suggest_skips_what_the_employer_list_follows(cli_env):
    _follow(cli_env, "Trustpilot")
    _posting(cli_env.jobs_dir, "jobindex", "Trustpilot", apply_url="https://job-boards.greenhouse.io/trustpilot/jobs/1")
    assert _suggest_core(profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)["suggestions"] == []


@responses.activate
def test_suggest_with_probe_reads_unknown_career_pages(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Acme", apply_url="https://careers.acme.dk/jobs/1")
    responses.add(responses.GET, "https://careers.acme.dk/jobs/1",
                  body='<a href="https://acme.recruitee.com/o/data">Apply</a>')
    responses.add(responses.GET, "https://acme.recruitee.com/api/offers/", json={"offers": [{"id": 1}]})

    result = _suggest_core(probe=True, profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)

    assert [(s["company"], s["platform"], s["entry"]) for s in result["suggestions"]] == [("Acme", "recruitee", "acme")]


# --- issue #256 ---------------------------------------------------------------

_HR_FIXTURES = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "hr_manager"
_ANDEL_AD = "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=277&ProjectId=191063&DepartmentId=21862&MediaId=5558"
_FEED = "https://api.hr-manager.net/JobPortal.svc/{}/PositionList/json/"
_AD_PAGES = re.compile(r"https://candidate\.hr-manager\.net/ApplicationInit\.aspx")


def _fixture(name):
    return (_HR_FIXTURES / name).read_text(encoding="utf-8")


def _suggest(cli_env, **kw):
    write_config(cli_env.profile_dir, {"role_targets": ["data"], "location": "x"})
    return _suggest_core(probe=True, profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir, **kw)


def _hr_feed(alias, items=({"Id": 1},)):
    responses.add(responses.GET, _FEED.format(alias),
                  json={"CustomerAlias": alias, "TransactionStatus": {"StatusCode": 0}, "Items": list(items)})


@responses.activate
def test_an_hr_manager_cid_link_gives_the_alias_from_its_ad_page(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Andel Energi", apply_url=_ANDEL_AD)
    _posting(cli_env.jobs_dir, "jobindex", "Andel Energi", apply_url=_ANDEL_AD.replace("5558", "5559"), title="Data Engineer")
    responses.add(responses.GET, _AD_PAGES, body=_fixture("ad_page_with_list_link.html"))
    _hr_feed("andel")

    result = _suggest(cli_env)

    assert [(s["company"], s["config_key"], s["entry"], s["postings"]) for s in result["suggestions"]] == \
        [("Andel Energi", "hr_manager_aliases", "andel", 2)]
    # one lookup of the employer, whatever the number of its postings
    assert len([c for c in responses.calls if "ApplicationInit" in c.request.url]) == 1


@responses.activate
def test_two_companies_with_the_same_cid_cost_one_lookup(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Andel Energi", apply_url=_ANDEL_AD)
    _posting(cli_env.jobs_dir, "jobindex", "Andel", apply_url=_ANDEL_AD.replace("5558", "5559"))
    responses.add(responses.GET, _AD_PAGES, body=_fixture("ad_page_with_list_link.html"))
    _hr_feed("andel")

    _suggest(cli_env)

    assert len([c for c in responses.calls if "ApplicationInit" in c.request.url]) == 1


@responses.activate
def test_an_hr_manager_cid_with_no_alias_on_the_page_falls_back_to_the_name(cli_env):
    link = "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1202&ProjectId=144266&DepartmentId=18956&MediaId=5"
    _posting(cli_env.jobs_dir, "jobindex", "nemlig.com", apply_url=link)
    responses.add(responses.GET, _AD_PAGES, body=_fixture("ad_page_without_alias.html"))
    responses.add(responses.GET, _FEED.format("nemligcom"), status=400)
    responses.add(responses.GET, _FEED.format("nemlig-com"), status=400)
    _hr_feed("nemlig")
    _no_board(r"https://boards-api\.greenhouse\.io/.*", r"https://api(\.eu)?\.lever\.co/.*",
              r"https://api\.ashbyhq\.com/.*", r"https://[a-z-]+\.(recruitee|teamtailor)\.com/.*",
              r"https://apply\.workable\.com/.*")

    result = _suggest(cli_env)

    assert [(s["config_key"], s["entry"]) for s in result["suggestions"]] == [("hr_manager_aliases", "nemlig")]


@responses.activate
def test_skip_advertisement_is_never_requested(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Andel Energi", apply_url=_ANDEL_AD + "&SkipAdvertisement=True")
    responses.add(responses.GET, _AD_PAGES, body=_fixture("ad_page_with_list_link.html"))
    _hr_feed("andel")

    result = _suggest(cli_env)

    assert result["suggestions"]
    assert not any("skipadvertisement" in c.request.url.lower() for c in responses.calls)


@responses.activate
def test_a_company_without_usable_links_is_found_by_its_name(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Trustpilot", apply_url="https://www.glassdoor.com/job-listing/1",
             url="https://carbontalent.carbondatasolutions.com/jobs/imp-greenhouse-data-science-manager-c6e724")
    responses.add(responses.GET, "https://boards-api.greenhouse.io/v1/boards/trustpilot/jobs",
                  json={"jobs": [{"id": 1, "title": "Data Scientist"}]})  # the title queued for it

    result = _suggest(cli_env)

    assert [(s["company"], s["config_key"], s["entry"]) for s in result["suggestions"]] == \
        [("Trustpilot", "greenhouse_boards", "trustpilot")]
    assert result["unresolved"] == []


@responses.activate
def test_a_company_already_read_from_a_feed_is_not_name_probed(cli_env):
    _posting(cli_env.jobs_dir, "greenhouse", "Trustpilot")

    result = _suggest(cli_env)

    assert result["suggestions"] == []
    assert not responses.calls


@responses.activate
@pytest.mark.parametrize("link", [
    "https://jobs.workable.com/view/abc", "https://www.it-jobbank.dk/jobannonce/1",
    "https://www.jobunivers.dk/stilling/1", "https://job.experis.dk/jobs/1",
])
def test_job_boards_are_never_career_sites(cli_env, link):
    _posting(cli_env.jobs_dir, "jobindex", "Acme", apply_url=link)
    responses.add(responses.GET, re.compile(".*"),
                  body='<script type="application/ld+json">{"@type": "JobPosting"}</script>', status=404)

    result = _suggest(cli_env)

    assert result["suggestions"] == []
    assert not any(urlparse(c.request.url).netloc == urlparse(link).netloc for c in responses.calls)


@responses.activate
def test_a_teamtailor_link_whose_feed_is_404_is_dropped(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "TT", apply_url="https://tt.teamtailor.com/jobs/1-x")
    _no_board(r"https://tt\.teamtailor\.com/.*", r"https://boards-api\.greenhouse\.io/.*",
              r"https://api(\.eu)?\.lever\.co/.*", r"https://api\.ashbyhq\.com/.*",
              r"https://[a-z-]+\.(recruitee|teamtailor)\.com/.*", r"https://apply\.workable\.com/.*",
              r"https://api\.hr-manager\.net/.*")

    result = _suggest(cli_env, add=True)

    assert result["suggestions"] == [] and result["added"] == []


@responses.activate
def test_a_teamtailor_link_whose_feed_lists_jobs_is_kept(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "TT", apply_url="https://tt.teamtailor.com/jobs/1-x")
    responses.add(responses.GET, "https://tt.teamtailor.com/jobs.json", json={"items": [{"id": 1}]})

    result = _suggest(cli_env)

    assert [(s["config_key"], s["entry"]) for s in result["suggestions"]] == [("teamtailor_companies", "tt")]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def test_add_cli_prints_each_result_with_its_evidence_and_records_it(cli_env):
    result = CliRunner().invoke(cli, ["companies", "add", "https://jobs.ashbyhq.com/pleo", "--no-probe", "Nobody"])
    text = result_text(result)
    assert result.exit_code == 0, text
    assert "Pleo: ashby:pleo" in text and "Ashby board link" in text
    assert "Nobody: unresolved" in text and "no job feed found" in text
    assert [c.name for c in _list(cli_env.profile_dir)] == ["Pleo", "Nobody"]


def test_add_cli_dry_run_says_so_and_writes_nothing(cli_env):
    result = CliRunner().invoke(cli, ["companies", "add", "--dry-run", "https://jobs.ashbyhq.com/pleo"])
    assert result.exit_code == 0, result_text(result)
    assert "--dry-run" in result_text(result) and not (cli_env.profile_dir / "companies.json").exists()


def test_bare_companies_lists_the_employers_with_a_status_symbol(cli_env):
    CliRunner().invoke(cli, ["companies", "add", "--no-probe", "https://jobs.ashbyhq.com/pleo", "Nobody"])
    for args in (["companies"], ["companies", "list"]):
        result = CliRunner().invoke(cli, args)
        text = result_text(result)
        assert result.exit_code == 0, text
        assert "✓ Pleo  ashby:pleo  manual" in text
        assert "? Nobody  manual  no job feed found" in text
        assert "1 followed, 0 unfollowable, 1 unresolved" in text
    only = result_text(CliRunner().invoke(cli, ["companies", "list", "--status", "unresolved"]))
    assert "Nobody" in only and "Pleo" not in only


def test_list_cli_on_an_empty_list_says_how_to_start(cli_env):
    text = result_text(CliRunner().invoke(cli, ["companies"]))
    assert "companies add" in text


def test_remove_cli_unfollows(cli_env):
    CliRunner().invoke(cli, ["companies", "add", "--no-probe", "https://jobs.ashbyhq.com/pleo"])
    result = CliRunner().invoke(cli, ["companies", "remove", "pleo"])
    assert result.exit_code == 0 and "Removed Pleo." in result_text(result)
    assert _list(cli_env.profile_dir) == []
    assert CliRunner().invoke(cli, ["companies", "remove", "pleo"]).exit_code == 1


def test_why_cli_shows_everything_known(cli_env):
    CliRunner().invoke(cli, ["companies", "add", "--no-probe", "https://jobs.ashbyhq.com/pleo"])
    _posting(cli_env.jobs_dir, "thehub", "Pleo")
    result = CliRunner().invoke(cli, ["companies", "why", "Pleo"])
    text = result_text(result)
    assert result.exit_code == 0, text
    for fragment in ("ashby:pleo", "found via:    manual", "evidence:", "first seen:", "postings:     1 (thehub 1)"):
        assert fragment in text
    assert CliRunner().invoke(cli, ["companies", "why", "Ghost"]).exit_code == 1


def test_a_broken_companies_file_is_a_clear_error(cli_env):
    (cli_env.profile_dir / "companies.json").write_text("{nope")
    result = CliRunner().invoke(cli, ["companies"])
    assert result.exit_code == 1 and "companies.json" in result_text(result)


@responses.activate
def test_suggest_with_probe_follows_a_pinpoint_link(cli_env):
    _posting(cli_env.jobs_dir, "jobindex", "Acme", apply_url="https://careers.acme.dk/jobs/1")
    responses.add(responses.GET, "https://careers.acme.dk/jobs/1",
                  body='<a href="https://acme.pinpointhq.com/en/postings/abc">Apply</a>')
    responses.add(responses.GET, "https://acme.pinpointhq.com/postings.json", json={"data": [{"id": "1"}]})

    result = _suggest_core(probe=True, profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)

    assert [(s["company"], s["platform"], s["entry"], s["config_key"]) for s in result["suggestions"]] == [
        ("Acme", "pinpoint", "acme", "pinpoint_companies")]


# --------------------------------------------------------------------------- #
# resolve follows careers links (home page -> careers page -> job system)
# --------------------------------------------------------------------------- #

def _page(url, body, **kw):
    responses.add(responses.GET, url, body=body, **kw)


@responses.activate
def test_an_employer_home_page_is_followed_to_its_careers_page(cli_env):
    _page("https://www.bec.dk/", '<a href="/om-os">Om os</a><a href="/ledige-stillinger/">Ledige stillinger</a>')
    _page("https://www.bec.dk/ledige-stillinger/", '<a href="https://candidate.hr-manager.net/Agent/Subscription.aspx?customer=bec">Ansog</a>')

    [found] = companies_cmd._resolve_core(["www.bec.dk"])["results"]

    assert (found["platform"], found["entry"]) == ("hr_manager", "bec")
    assert found["evidence"].startswith("www.bec.dk → https://www.bec.dk/ledige-stillinger/ links to it")


@responses.activate
def test_a_second_hop_is_followed_from_the_careers_page(cli_env):
    _page("https://famly.co/", '<a href="/about/careers">Careers</a>')
    _page("https://famly.co/about/careers", '<a href="/open-positions">See open positions</a>')
    _page("https://famly.co/open-positions", '<a href="https://famly.recruitee.com/o/engineer">Engineer</a>')
    responses.add(responses.GET, "https://famly.recruitee.com/api/offers/", json={"offers": [{"id": 1}]})

    [found] = companies_cmd._resolve_core(["famly.co"])["results"]

    assert (found["platform"], found["entry"]) == ("recruitee", "famly")
    assert "https://famly.co/about/careers → https://famly.co/open-positions" in found["evidence"]


@responses.activate
def test_a_deep_link_on_the_employers_site_falls_back_to_the_home_page(cli_env):
    _page("https://www.pwc.dk/da/om-os/team.html", "<p>A team</p>")
    _page("https://www.pwc.dk/", '<a href="/da/karriere.html">Karriere</a>')
    _page("https://www.pwc.dk/da/karriere.html", '<a href="https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers">Jobs</a>')

    [found] = companies_cmd._resolve_core(["https://www.pwc.dk/da/om-os/team.html"])["results"]

    assert found["platform"] == "career_sites"
    assert "https://www.pwc.dk/da/karriere.html" in found["evidence"]


@responses.activate
def test_a_page_with_a_platform_is_not_followed_further(cli_env):
    _page("https://careers.acme.dk/", '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
                                       '<a href="/jobs">Jobs</a>')

    [found] = companies_cmd._resolve_core(["https://careers.acme.dk/"])["results"]

    assert found["entry"] == "acme"
    assert len(responses.calls) == 1


@responses.activate
def test_nothing_is_found_when_no_careers_page_shows_a_job_system(cli_env):
    _page("https://acme.dk/", '<a href="/karriere">Karriere</a><a href="https://www.jobindex.dk/acme">Jobs</a>')
    _page("https://acme.dk/karriere", "<p>Intet her</p>")

    [found] = companies_cmd._resolve_core(["acme.dk"])["results"]

    assert found["platform"] is None
    assert not any("jobindex" in c.request.url for c in responses.calls)


@responses.activate
def test_following_is_capped(cli_env):
    links = "".join(f'<a href="/careers/{i}">Careers {i}</a>' for i in range(20))
    _page("https://acme.dk/", links)
    responses.add(responses.GET, re.compile(r"https://acme\.dk/careers/.*"), body="<p>nothing</p>")

    [found] = companies_cmd._resolve_core(["acme.dk"])["results"]

    assert found["platform"] is None
    assert len(responses.calls) <= 1 + companies_cmd._MAX_CAREERS_PAGES + companies_cmd._MAX_SECOND_HOP + 1


@pytest.mark.usefixtures("obey_robots")
@pytest.mark.real_robots
@responses.activate
def test_a_careers_page_blocked_by_robots_is_skipped(cli_env):
    responses.add(responses.GET, "https://acme.dk/robots.txt", body="User-agent: *\nDisallow: /karriere\n")
    _page("https://acme.dk/", '<a href="/karriere">Karriere</a><a href="/jobs">Jobs</a>')
    _page("https://acme.dk/karriere", '<a href="https://acme.recruitee.com/">x</a>')
    _page("https://acme.dk/jobs", '<a href="https://boards.greenhouse.io/acme">Apply</a>')

    [found] = companies_cmd._resolve_core(["acme.dk"])["results"]

    assert (found["platform"], found["entry"]) == ("greenhouse", "acme")
    assert not any(c.request.url.endswith("/karriere") for c in responses.calls)


@pytest.mark.real_robots
@responses.activate
def test_a_home_page_blocked_by_robots_resolves_to_nothing(cli_env):
    responses.add(responses.GET, "https://acme.dk/robots.txt", body="User-agent: *\nDisallow: /\n")

    [found] = companies_cmd._resolve_core(["acme.dk"])["results"]

    assert found["platform"] is None


# --- dormant employers ----------------------------------------------------------------------------------

def _go_dormant(cli_env, name="Acme"):
    from datetime import datetime, timezone

    items = companies_store.load(cli_env.profile_dir)
    companies_store.record(items, name, feed=("lever", "acme"), status="followed", found_via="jobindex",
                           now="2026-01-01T00:00:00+00:00")
    companies_store.retire_idle(items, 90, datetime.now(timezone.utc))
    companies_store.save(cli_env.profile_dir, items)


def test_list_shows_dormant_employers_with_their_reason_and_counts_them(cli_env):
    _go_dormant(cli_env)
    text = result_text(CliRunner().invoke(cli, ["companies"]))
    assert "· Acme  lever:acme  jobindex  no relevant job in 90 days" in text
    assert "0 followed, 0 unfollowable, 0 unresolved, 1 dormant" in text
    only = result_text(CliRunner().invoke(cli, ["companies", "list", "--status", "dormant"]))
    assert "Acme" in only


def test_why_explains_a_dormant_employer(cli_env):
    _go_dormant(cli_env)
    text = result_text(CliRunner().invoke(cli, ["companies", "why", "Acme"]))
    assert "status:       dormant" in text and "no relevant job in 90 days" in text
    assert "follows it again" in text and "last relevant: never" in text


def test_add_on_a_dormant_employer_follows_it_again(cli_env):
    _go_dormant(cli_env)
    result = companies_cmd._add_core(["Acme"], probe=False, profile_dir=cli_env.profile_dir)
    acme = companies_store.find(companies_store.load(cli_env.profile_dir), "Acme")
    assert (acme.status, acme.reason, acme.feed.id, acme.found_via) == ("followed", None, "acme", "manual")
    assert acme.last_relevant is not None
    assert result["results"][0]["status"] == "followed" and result["results"][0]["new"] is False


def test_classify_skips_a_malformed_link_and_follows_the_good_one():
    from door.commands import companies as companies_cmd
    company = {"company": "Acme", "sources": {"jobindex"}, "postings": 1,
               "links": ['https://accounts.google.com&quot;,null,[[null,&quot;https://x&quot;]]',
                         "http://[bad", "https://boards.greenhouse.io/acme"]}
    kind, item = companies_cmd._classify(None, company, set())
    assert kind == "suggestions"
    assert item["platform"] == "greenhouse" if "platform" in item else "greenhouse" in str(item)


# --------------------------------------------------------------------------- #
# merge, aliases (#314)
# --------------------------------------------------------------------------- #

def _dupes(profile_dir):
    items = [
        companies_store.Company(name="LEGO", feed=companies_store.Feed(platform="lever", id="lego"),
                                status="followed", found_via="manual"),
        companies_store.Company(name="LEGO System A/S", feed=companies_store.Feed(platform="lever", id="LEGO"),
                                status="followed", found_via="linkedin"),
        companies_store.Company(name="Tryg", status="unresolved", found_via="jobindex", aliases=["Tryg Forsikring"]),
        companies_store.Company(name="Tryg Forsikring A/S", status="unfollowable", found_via="linkedin", reason="x"),
        companies_store.Company(name="Solo", status="unresolved", found_via="linkedin"),
    ]
    companies_store.save(profile_dir, items)


def test_merge_without_names_proposes_the_duplicates_and_writes_nothing(cli_env):
    _dupes(cli_env.profile_dir)
    before = (cli_env.profile_dir / "companies.json").read_bytes()

    result = companies_cmd._merge_core(profile_dir=cli_env.profile_dir)

    assert {"names": ["LEGO", "LEGO System A/S"], "reason": "same feed"} in result["candidates"]
    assert {"names": ["Tryg", "Tryg Forsikring A/S"], "reason": "same name"} in result["candidates"]
    assert len(result["candidates"]) == 2
    assert (cli_env.profile_dir / "companies.json").read_bytes() == before


def test_merge_two_names_folds_the_second_into_the_first_and_saves(cli_env):
    _dupes(cli_env.profile_dir)

    result = companies_cmd._merge_core(["Tryg", "Tryg Forsikring A/S"], profile_dir=cli_env.profile_dir)

    assert result["removed"] == "Tryg Forsikring A/S" and result["merged"]["name"] == "Tryg"
    assert result["merged"]["aliases"] == ["Tryg Forsikring"]
    assert [c.name for c in _list(cli_env.profile_dir)] == ["LEGO", "LEGO System A/S", "Tryg", "Solo"]


def test_merge_one_name_is_a_usage_error_and_refusals_are_errors(cli_env):
    _dupes(cli_env.profile_dir)
    with pytest.raises(ValueError):
        companies_cmd._merge_core(["Tryg"], profile_dir=cli_env.profile_dir)
    with pytest.raises(companies_store.CompaniesError):
        companies_cmd._merge_core(["Tryg", "Nobody"], profile_dir=cli_env.profile_dir)


def test_merge_is_taken_under_the_ledger_lock(cli_env):
    assert companies_cmd._merge_core.__wrapped__ is not None


def test_merge_cli_proposes_then_merges(cli_env):
    _dupes(cli_env.profile_dir)
    proposal = CliRunner().invoke(cli, ["companies", "merge"])
    text = result_text(proposal)
    assert proposal.exit_code == 0 and "LEGO, LEGO System A/S" in text and "same feed" in text
    assert len(_list(cli_env.profile_dir)) == 5

    done = CliRunner().invoke(cli, ["companies", "merge", "Tryg", "Tryg Forsikring A/S"])
    assert done.exit_code == 0 and "Merged Tryg Forsikring A/S into Tryg." in result_text(done)
    assert len(_list(cli_env.profile_dir)) == 4

    assert CliRunner().invoke(cli, ["companies", "merge", "Tryg"]).exit_code != 0
    bad = CliRunner().invoke(cli, ["companies", "merge", "Tryg", "Nobody"])
    assert bad.exit_code == 1 and "Error:" in result_text(bad)
    same = CliRunner().invoke(cli, ["companies", "merge", "LEGO", "LEGO System A/S"])
    assert same.exit_code == 0  # same feed, one followed feed: allowed


def test_merge_cli_with_nothing_to_merge(cli_env):
    companies_cmd._add_core(["Nobody"], probe=False, profile_dir=cli_env.profile_dir)
    assert "No duplicate employers." in result_text(CliRunner().invoke(cli, ["companies", "merge"]))


def test_list_and_why_show_the_aliases(cli_env):
    _dupes(cli_env.profile_dir)
    listing = result_text(CliRunner().invoke(cli, ["companies"]))
    assert "Tryg" in listing and "aka: Tryg Forsikring" in listing
    why = result_text(CliRunner().invoke(cli, ["companies", "why", "Tryg Forsikring"]))
    assert "aliases:" in why and "Tryg Forsikring" in why


def test_why_counts_postings_by_employer_or_by_name_or_alias_once(cli_env):
    _dupes(cli_env.profile_dir)
    _posting(cli_env.jobs_dir, "jobindex", "Tryg", x=1)                                   # name
    _posting(cli_env.jobs_dir, "jobindex", "Tryg Forsikring", x=1, y=2)                # alias by name_key
    _posting(cli_env.jobs_dir, "thehub", "Whatever Agency", employer="Tryg")               # stamped
    _posting(cli_env.jobs_dir, "thehub", "Tryg", x=1, y=2, z=3, employer="Tryg")           # both: once
    _posting(cli_env.jobs_dir, "thehub", "Someone Else")

    result = companies_cmd._why_core("Tryg", profile_dir=cli_env.profile_dir, jobs_dir=cli_env.jobs_dir)

    assert result["postings"] == 4 and result["by_source"] == {"jobindex": 2, "thehub": 2}


# --------------------------------------------------------------------------- #
# two employers on one platform stay two (#436)
# --------------------------------------------------------------------------- #

def _emply_page(tenant, head):
    ads = "".join(f'<a href="https://{tenant}.career.emply.com/en/ad/job-{i}/x{i}y">Job {i}</a>' for i in range(4))
    _page(f"https://{tenant}.career.emply.com/en", f"<html><head>{head}</head><body>{ads}</body></html>")


@responses.activate
def test_two_employers_on_emply_are_two_entries_each_named_by_its_page(cli_env):
    _emply_page("dca", '<meta property="og:site_name" content="Emply"><title>DanChurchAid - Ledige stillinger</title>')
    _emply_page("rodekors", '<meta property="og:site_name" content="Dansk Røde Kors">')
    responses.add(responses.GET, re.compile(r"https://\w+\.career\.emply\.com/.*"), status=404)

    result = companies_cmd._add_core(["https://dca.career.emply.com/en", "https://rodekors.career.emply.com/en"],
                                     profile_dir=cli_env.profile_dir)

    assert [r["name"] for r in result["results"]] == ["DanChurchAid", "Dansk Røde Kors"]
    dca, rk = _list(cli_env.profile_dir)
    assert dca.status == rk.status == "followed"
    assert (dca.feed.platform, dca.feed.id) == ("emply", "dca") and (rk.feed.platform, rk.feed.id) == ("emply", "rodekors")


@responses.activate
def test_an_emply_page_that_names_nobody_gives_the_tenant_not_the_platform(cli_env):
    _emply_page("dca", "<title>Emply</title>")
    _emply_page("rodekors", "")
    responses.add(responses.GET, re.compile(r"https://\w+\.career\.emply\.com/.*"), status=404)

    companies_cmd._add_core(["https://dca.career.emply.com/en", "https://rodekors.career.emply.com/en"],
                            profile_dir=cli_env.profile_dir)

    assert [c.name for c in _list(cli_env.profile_dir)] == ["Dca", "Rodekors"]


@responses.activate
def test_a_varbi_ad_link_is_named_by_the_board_not_the_ad(cli_env):
    """#525: the link is an ad page, whose title is the job's; the employer is on the tenant's board page."""
    _page("https://ki.varbi.com/", "<html><head><title>Lediga anst\u00e4llningar vid Karolinska Institutet</title></head></html>")
    _page("https://ki.varbi.com/en/what:job/jobID:985204/",
          "<html><head><title>Research Assistant in Diabetes Research</title></head></html>")
    responses.add(responses.GET, "https://ki.varbi.com/what:rssfeed/", body="<rss><channel/></rss>")

    result = companies_cmd._add_core(["https://ki.varbi.com/en/what:job/jobID:985204/"], profile_dir=cli_env.profile_dir)

    assert [r["name"] for r in result["results"]] == ["Karolinska Institutet"]
    (karolinska,) = _list(cli_env.profile_dir)
    assert (karolinska.feed.platform, karolinska.feed.id) == ("varbi", "ki")


_RM = "https://web103.reachmee.com"
_RM_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "reachmee"


@responses.activate
def test_a_reachmee_ad_link_is_named_by_the_list_page_not_the_ad(cli_env):
    """#527: the ad page is titled by the job; the employer is the prefix of the list page's title."""
    link = f"{_RM}/ext/I003/354/job?site=5&lang=SE&validator=5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a&job_id=12975"
    responses.add(responses.GET, f"{_RM}/customerjs/I003-354-5.js", body=(_RM_FX / "customerjs_sv.js").read_text())
    _page(f"{_RM}/ext/I003/354/main", (_RM_FX / "list_sv.html").read_text())
    _page(link, (_RM_FX / "job_sv_12975.html").read_text())

    result = companies_cmd._add_core([link], profile_dir=cli_env.profile_dir)

    assert [r["name"] for r in result["results"]] == ["\u00d6rebro universitet"]
    (oru,) = _list(cli_env.profile_dir)
    assert (oru.feed.platform, oru.feed.id) == ("reachmee", "I003/354/5")


@responses.activate
def test_a_reachmee_list_with_no_open_ads_still_names_the_employer(cli_env):
    link = f"{_RM}/ext/I021/1746/main?site=6&validator=6b6b6b6b6b6b6b6b6b6b6b6b6b6b6b6b&lang=SE"
    responses.add(responses.GET, f"{_RM}/customerjs/I021-1746-6.js", body=(_RM_FX / "customerjs_empty.js").read_text())
    _page(f"{_RM}/ext/I021/1746/main", (_RM_FX / "list_empty.html").read_text())

    result = companies_cmd._add_core([link], profile_dir=cli_env.profile_dir)

    assert [r["name"] for r in result["results"]] == ["Arbetsgivarverket"]


# --------------------------------------------------------------------------- #
# a name never follows a demo tenant, a namesake abroad or a dead feed (#435)
# --------------------------------------------------------------------------- #

_FEEDS = TESTS_DIR / "scrapers" / "feeds" / "fixtures"


@responses.activate
@pytest.mark.parametrize("name, url, fixture", [
    ("Novo Nordisk", "https://novonordisk.pinpointhq.com/postings.json", "pinpoint/demo_tenant.json"),
    ("KPMG", "https://kpmg.pinpointhq.com/postings.json", "pinpoint/demo_tenant.json"),
    ("Maersk", "https://maersk.teamtailor.com/jobs.json", "teamtailor/demo_tenant.json"),
    ("EY", "https://ey.recruitee.com/api/offers/", "recruitee/sample_tenant.json"),
    ("WTW", re.compile(r"https://api\.smartrecruiters\.com/v1/companies/wtw/postings.*"),
     "smartrecruiters/unrelated_us_account.json"),
])
def test_add_by_name_never_follows_a_demo_tenant_or_a_namesake_abroad(cli_env, name, url, fixture):
    write_config(cli_env.profile_dir, {"role_targets": ["data"], "location": "Copenhagen", "min_score": 0.6})
    responses.add(responses.GET, url, body=(_FEEDS / fixture).read_text())
    _no_board(r"https://.*")

    [item] = companies_cmd._add_core([name], dry_run=True, profile_dir=cli_env.profile_dir)["results"]

    assert (item["status"], item["entry"]) == ("unresolved", None)
    assert "demo" in item["reason"] or "location" in item["reason"]


@responses.activate
def test_add_by_name_still_follows_a_feed_with_a_job_in_the_profiles_place(cli_env):
    write_config(cli_env.profile_dir, {"role_targets": ["data"], "location": "Copenhagen", "min_score": 0.6})
    responses.add(responses.GET, "https://boards-api.greenhouse.io/v1/boards/trustpilot/jobs",
                  json={"jobs": [{"title": "Data Engineer", "location": {"name": "Copenhagen, Denmark"}}]})
    _no_board(r"https://.*")

    [item] = companies_cmd._add_core(["Trustpilot"], dry_run=True, profile_dir=cli_env.profile_dir)["results"]

    assert (item["status"], item["platform"], item["entry"]) == ("followed", "greenhouse", "trustpilot")


@responses.activate
def test_add_two_names_on_feeds_with_the_same_jobs_follows_neither(cli_env):
    jobs = {"data": [{"title": t, "location": {"name": "Copenhagen"}} for t in ("Head of DEI", "Marketing Manager", "Intern")]}
    for slug in ("novonordisk", "kpmg"):
        responses.add(responses.GET, f"https://{slug}.pinpointhq.com/postings.json", json=jobs)
    _no_board(r"https://.*")

    results = companies_cmd._add_core(["Novo Nordisk", "KPMG"], dry_run=True, profile_dir=cli_env.profile_dir)["results"]

    assert [r["status"] for r in results] == ["unresolved", "unresolved"]
    assert all("same jobs" in r["reason"] for r in results)


@responses.activate
def test_add_a_dead_hr_manager_alias_is_unresolved_with_the_reason(cli_env):
    responses.add(responses.GET, re.compile(r"https://api\.hr-manager\.net/JobPortal\.svc/mfs/.*"), status=400,
                  body=(_FEEDS / "hr_manager" / "dead_alias_400.json").read_text())

    [item] = companies_cmd._add_core(["https://candidate.hr-manager.net/vacancies/list.aspx?customer=MFS"],
                                     dry_run=True, profile_dir=cli_env.profile_dir)["results"]

    assert (item["status"], item["entry"]) == ("unresolved", None) and "400" in item["reason"]


# --------------------------------------------------------------------------- #
# a followed employer whose feed collect could not read says so (#437)
# --------------------------------------------------------------------------- #

def _blocked(cli_env, outcome="blocked", reason="dca.example: bot protection; not attempted"):
    items = companies_store.load(cli_env.profile_dir)
    acme, _ = companies_store.record(items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual",
                                     now="2026-01-01T00:00:00+00:00")
    companies_store.set_collect_problem(acme, outcome, reason, "2026-01-02T00:00:00+00:00")
    companies_store.save(cli_env.profile_dir, items)


def test_list_shows_why_a_followed_feed_could_not_be_read(cli_env):
    _blocked(cli_env)
    text = result_text(CliRunner().invoke(cli, ["companies"]))
    assert "✓ Acme  lever:acme  manual  blocked: dca.example: bot protection; not attempted" in text


def test_list_core_carries_the_problem_for_the_tool_and_the_app(cli_env):
    _blocked(cli_env, "failed", "error fetching 'acme': 500")
    [row] = companies_cmd._list_core(profile_dir=cli_env.profile_dir)["companies"]
    assert row["collect_problem"] == {"at": "2026-01-02T00:00:00+00:00", "outcome": "failed",
                                      "reason": "error fetching 'acme': 500"}


def test_why_shows_the_collect_problem(cli_env):
    _blocked(cli_env)
    text = result_text(CliRunner().invoke(cli, ["companies", "why", "Acme"]))
    assert "collect:" in text and "blocked" in text and "bot protection" in text


# --------------------------------------------------------------------------- #
# the Danish universities (#431)
# --------------------------------------------------------------------------- #

_ORACLE_ANY_SITES = re.compile(r"https://[a-z0-9.\-]+\.oraclecloud\.com/hcmRestApi/resources/latest/recruitingCESites.*")


@responses.activate
def test_the_vacancy_page_of_itu_leads_to_its_hr_manager_alias(cli_env):
    """ITU links its ads by customer number and its job agent by the scheme-less `//delta.hr-manager.net`."""
    responses.add(responses.GET, "https://en.itu.dk/About-ITU/Vacancies", body=_fixture("itu_vacancies.html"))
    _hr_feed("ituniversitetet", [{"Id": 1, "AdvertisementUrl": "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=119&ProjectId=1"}])

    [found] = companies_cmd._resolve_core(["https://en.itu.dk/About-ITU/Vacancies"])["results"]

    assert (found["platform"], found["entry"], found["config_key"]) == ("hr_manager", "ituniversitetet", "hr_manager_aliases")


@responses.activate
def test_ruc_is_followed_from_its_hr_manager_feed_link(cli_env):
    """RUC's alias is `ruc`; a name only reaches it when a queued job or the profile's city is in its feed."""
    _hr_feed("ruc", [{"Id": 9, "AdvertisementUrl": "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=1310&ProjectId=2"}])

    [found] = companies_cmd._resolve_core([_FEED.format("ruc")])["results"]

    assert (found["platform"], found["entry"]) == ("hr_manager", "ruc")


@responses.activate
@pytest.mark.parametrize("name, page, site, entry", [
    ("DTU", "https://www.dtu.dk/english/about/job-and-career/vacancies",
     "https://efzu.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions?lastSelectedFacet=POSTING_DATES",
     "efzu.fa.em2.oraclecloud.com/CX_1"),
    ("SDU", "https://www.sdu.dk/en/service/ledige_stillinger",
     "https://fa-eosd-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions",
     "fa-eosd-saasfaprod1.fa.ocs.oraclecloud.com/CX_1001"),
])
def test_dtu_and_sdu_vacancy_pages_are_followed_through_oracle_hcm(cli_env, name, page, site, entry):
    site_number = entry.split("/")[1]
    responses.add(responses.GET, page, body=f'<html><body><a href="{site}" class="button">See our vacant positions</a></body></html>')
    responses.add(responses.GET, _ORACLE_ANY_SITES, json={"items": [{"SiteNumber": site_number, "StatusCode": "ORA_ACTIVE"}]})

    [found] = companies_cmd._resolve_core([page])["results"]

    assert (found["platform"], found["entry"], found["config_key"]) == ("oracle_hcm", entry, "oracle_hcm_companies")


@responses.activate
def test_aarhus_universitys_vacancy_page_is_followed_as_an_embedded_emply_list(cli_env):
    page = "https://international.au.dk/about/profile/vacant-positions/"
    responses.add(responses.GET, page, body=(_FEEDS / "emply" / "au_vacancies.html").read_text(encoding="utf-8"))
    write_config(cli_env.profile_dir, {"role_targets": ["physics"], "location": "Copenhagen, Denmark"})

    [item] = companies_cmd._add_core([page], profile_dir=cli_env.profile_dir)["results"]

    assert (item["status"], item["platform"], item["entry"]) == ("followed", "emply", page)
    assert item["name"] == "Aarhus University"
    assert companies_store.feed_config(cli_env.profile_dir) == {"emply_tenants": [page]}


def test_career_hosts_of_the_united_kingdom_join_a_two_label_ending():
    gb = set(companies_cmd._host_guesses("London"))
    assert {"careers.{s}.co.uk", "jobs.{s}.co.uk", "recruitment.{s}.co.uk", "vacancies.{s}.co.uk"} <= gb
