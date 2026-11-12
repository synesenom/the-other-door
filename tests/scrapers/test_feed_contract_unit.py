"""The feed-platform contract (issue #282): each feed site's module detects and confirms its own
feed, and the shared code names no platform outside the dispatcher's precedence tuple."""

import importlib
import re

import pytest

from door.core import ats_detect
from door.core.sites import FEED_SITES, SITES
from paths import REPO_ROOT


def _module(name):
    return importlib.import_module(SITES[name].module)


@pytest.mark.parametrize("site", sorted(FEED_SITES))
def test_a_feed_module_detects_urls_and_names_its_feed(site):
    module = _module(site)
    assert callable(module.detect_url) and callable(module.feed_url)
    assert module.detect_url("https://example.invalid/x") is None
    assert module.feed_url("nobody") is None or isinstance(module.feed_url("nobody"), str)


@pytest.mark.parametrize("site", sorted(FEED_SITES))
def test_name_probes_are_probes_with_a_url_a_key_and_evidence(site):
    probes = getattr(_module(site), "name_probes", lambda slug: [])("acme")
    for probe in probes:
        assert probe.url.startswith("https://") and "acme" in probe.url + probe.evidence
        assert probe.key is None or isinstance(probe.key, str)
        assert probe.evidence


def test_the_precedence_names_modules_that_exist():
    for name in ats_detect.PRECEDENCE:
        importlib.import_module(f"door.scrapers.feeds.{name}")
    assert set(FEED_SITES) <= set(ats_detect.PRECEDENCE)


def test_the_name_probes_keep_their_order():
    order = [(platform, probe.evidence) for platform, _slug, probe in ats_detect.name_probes(["acme"])]
    assert [p for p, _ in order] == [
        "greenhouse", "lever", "lever", "ashby", "recruitee", "pinpoint", "teamtailor", "workable", "smartrecruiters", "flatchr", "taleez"]
    assert "EU" in order[2][1]


def test_ats_detect_names_no_platform_outside_its_precedence_tuple():
    source = (REPO_ROOT / "src/door/core/ats_detect.py").read_text(encoding="utf-8")
    start = source.index("PRECEDENCE = (")
    rest = source[:start] + source[source.index(")", start) + 1:]
    names = ("greenhouse", "lever", "workable", "ashby", "recruitee", "pinpoint", "teamtailor", "smartrecruiters",
             "dayforce", "signatur", "successfactors", "hr_manager", "hr-manager", "workday", "oracle")
    found = [n for n in names if re.search(rf"(?i)\b{n}", rest)]
    assert not found, f"ats_detect.py names platforms outside PRECEDENCE: {found}"


def test_the_companies_command_holds_no_feed_endpoint():
    source = (REPO_ROOT / "src/door/commands/companies.py").read_text(encoding="utf-8")
    assert not re.findall(r"https://[^\"'\s]*(api|boards|hr-manager|workable|pinpoint|recruitee|teamtailor)", source)


# A portal that serves many employers names each posting's own (hr_manager: hospitals, agencies).
_MULTI_EMPLOYER = {"hr_manager"}


@pytest.mark.parametrize("site", sorted(n for n, s in SITES.items() if s.config_key and n not in _MULTI_EMPLOYER))
def test_a_single_employer_feed_labels_its_postings_with_the_followed_name(site):
    """Issue #291: collect hands the scrapers the followed names; each reads them through the SDK."""
    source = (REPO_ROOT / "src" / "door" / "scrapers" / "feeds" / f"{site}.py").read_text(encoding="utf-8")
    assert "followed_name(" in source, f"{site} ignores the followed employer's name"


# --------------------------------------------------------------------------- #
# Job ids (#313): <site>.<platform_id>, and a per-tenant id carries its tenant
# --------------------------------------------------------------------------- #

def _per_tenant_postings(site, host):
    """The mapper output of the same raw id `77` on tenant *host*, built from a synthetic item."""
    from datetime import datetime, timezone

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    module = _module(site)
    if site == "successfactors":
        link = f"https://{host}/job/Dev/77/"
        return module._to_posting({"title": "Dev", "link": link}, "Acme", module._folded_platform_id(link), now)
    if site == "teamtailor":
        return module._to_posting({"id": "uuid", "title": "Dev", "url": f"https://{host}/jobs/77-dev",
                                   "_jobposting": {"identifier": {"value": 77}}}, "Acme", now)
    if site == "pinpoint":
        base = f"https://{host}"
        return module._to_posting({"id": 77, "title": "Dev", "path": "/en/postings/x"}, "Acme", base, now)
    raise AssertionError(site)


@pytest.mark.parametrize("site", ["successfactors", "teamtailor", "pinpoint"])
def test_a_per_tenant_platform_id_differs_between_two_tenants(site):
    a = _per_tenant_postings(site, "one.example.com")
    b = _per_tenant_postings(site, "two.example.com")
    assert a["platform_id"] != b["platform_id"]
    assert a["id"] != b["id"]
    assert "one.example.com" in a["platform_id"]


@pytest.mark.parametrize("site", ["successfactors", "teamtailor", "pinpoint"])
def test_the_id_is_the_site_and_the_platform_id(site):
    from door.core.models import make_job_id

    posting = _per_tenant_postings(site, "one.example.com")
    assert posting["id"] == make_job_id(site, posting["platform_id"])
