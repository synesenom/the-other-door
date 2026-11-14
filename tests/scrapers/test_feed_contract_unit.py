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


def test_name_probes_go_platform_by_platform_in_precedence_order_each_probe_over_every_slug():
    probes = ats_detect.name_probes(["acme", "acme-dk"])
    platforms = list(dict.fromkeys(p for p, _slug, _probe in probes))
    assert platforms == [p for p in ats_detect.PRECEDENCE if p in platforms]
    lever = [(slug, probe.url) for p, slug, probe in probes if p == "lever"]
    assert [slug for slug, _ in lever] == ["acme", "acme-dk", "acme", "acme-dk"]   # both hosts, for every slug in turn
    assert lever[0][1] != lever[2][1]


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
