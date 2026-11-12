"""Unit tests for reading employer career sites through sitemaps and schema.org
JobPosting markup (issue #232). Pure helpers only."""

import pytest
from bs4 import BeautifulSoup

from door.scrapers.feeds import career_sites
from paths import TESTS_DIR

_FIX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "career_sites"

_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://x.dk/pages.xml</loc></sitemap>
  <sitemap><loc>https://x.dk/jobs-sitemap.xml</loc><lastmod>2026-10-01</lastmod></sitemap>
</sitemapindex>"""

_URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://x.dk/jobs/1</loc><lastmod>2026-10-05T10:00:00+02:00</lastmod></url>
  <url><loc>https://x.dk/jobs/2</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc> https://x.dk/about </loc></url>
</urlset>"""


def test_parse_sitemap_reads_an_index_and_a_urlset():
    kind, entries = career_sites._parse_sitemap(_INDEX)
    assert kind == "index" and [e[0] for e in entries] == ["https://x.dk/pages.xml", "https://x.dk/jobs-sitemap.xml"]
    kind, entries = career_sites._parse_sitemap(_URLSET)
    assert kind == "urlset"
    assert entries[0][0] == "https://x.dk/jobs/1" and entries[0][1].isoformat() == "2026-10-05T10:00:00+02:00"
    assert entries[1][1].isoformat() == "2026-08-01T00:00:00+00:00"
    assert entries[2] == ("https://x.dk/about", None)


def test_parse_sitemap_of_garbage_is_empty():
    assert career_sites._parse_sitemap("<html>not a sitemap</html>") == ("urlset", [])
    assert career_sites._parse_sitemap("not xml at all <") == ("urlset", [])


@pytest.mark.parametrize("url, job", [
    ("https://x.dk/jobs/1", True),
    ("https://x.dk/job-details/2026-1-data", True),
    ("https://x.dk/karriere/ledige-stillinger/data", True),
    ("https://x.dk/careers/position/7", True),
    ("https://x.dk/vacancies/7", True),
    ("https://x.dk/about", False),
    ("https://x.dk/", False),
])
def test_looks_like_a_job_page(url, job):
    assert career_sites._looks_like_job(url) is job


def test_job_postings_from_html_reads_js_escaped_markup_like_publicis_sapients():
    html = (_FIX / "ps_job_copenhagen.html").read_text(encoding="utf-8")
    [job] = career_sites._job_postings_from_html(html)
    assert job["title"] == "Data Science - Manager - Retail"
    assert job["datePosted"] == "2026-04-08T08:20:00Z"


def test_job_postings_from_html_finds_graphs_and_lists_and_skips_invalid_json():
    html = """
    <script type="application/ld+json">{"@graph": [{"@type": "Organization"}, {"@type": "JobPosting", "title": "A"}]}</script>
    <script type="application/ld+json">[{"@type": ["JobPosting"], "title": "B"}]</script>
    <script type="application/ld+json">{not json</script>
    <script type="application/ld+json">{"@type": "WebSite"}</script>
    """
    assert [j["title"] for j in career_sites._job_postings_from_html(html)] == ["A", "B"]


@pytest.mark.parametrize("location, text", [
    ({"@type": "Place", "address": {"addressLocality": "København", "addressRegion": "Hovedstaden", "addressCountry": "DK"}},
     "København, Hovedstaden, DK"),
    ({"address": {"streetAddress": "Vermundsgade 40 A Copenhagen  2100 Denmark", "addressRegion": "Others",
                  "addressCountry": "Denmark"}}, "Vermundsgade 40 A Copenhagen 2100 Denmark"),
    ([{"address": {"addressLocality": "Aarhus"}}, {"address": {"addressLocality": "Odense", "addressCountry": {"name": "Denmark"}}}],
     "Aarhus; Odense, Denmark"),
    ({"address": "Aalborg"}, "Aalborg"),
    (None, ""),
])
def test_location_text(location, text):
    assert career_sites._location_text({"jobLocation": location}) == text


def test_location_text_marks_telecommute():
    job = {"jobLocationType": "TELECOMMUTE", "applicantLocationRequirements": {"name": "Denmark"}}
    assert career_sites._location_text(job) == "Remote, Denmark"


@pytest.mark.parametrize("job, text", [
    ({"applicantLocationRequirements": {"@type": "Country", "name": "Germany"}}, "Germany"),
    ({"applicantLocationRequirements": [{"@type": "Country", "name": "Germany"},
                                        {"@type": "AdministrativeArea", "name": "Bavaria"}]}, "Germany; Bavaria"),
    ({"applicantLocationRequirements": "Germany"}, "Germany"),
    ({"applicantLocationRequirements": {"address": {"addressCountry": {"name": "Germany"}}}}, "Germany"),
    ({"applicantLocationRequirements": {"address": {"addressCountry": {"@id": "DE"}}}}, "DE"),
    ({"jobLocation": {"name": "Aarhus"}}, "Aarhus"),
    ({"jobLocation": {"name": "Aarhus"}, "applicantLocationRequirements": {"name": "Germany"}}, "Aarhus"),
])
def test_location_text_falls_back_to_applicant_location_requirements(job, text):
    assert career_sites._location_text(job) == text


@pytest.mark.parametrize("html, challenge", [
    ("<title>Just a moment...</title>", True),
    ("<div id='cf-challenge-running'>", True),
    ("<title>Authenticating...</title> akamai", True),
    ("<title>Data Scientist</title>", False),
    ("<title>Please verify you are human</title><div class='captcha-box'></div>", True),
    # a form that loads reCAPTCHA's script is not a challenge page (Emply's ad pages, #437)
    ('<head><script src="https://www.google.com/recaptcha/api.js?render=x" async defer></script>'
     "<title>Data Scientist</title></head>", False),
    ('<script src="https://js.hcaptcha.com/1/api.js"></script><title>Data Scientist</title>', False),
])
def test_is_challenge(html, challenge):
    assert career_sites._is_challenge(html, {}) is challenge


def test_a_cf_mitigated_header_is_a_challenge():
    assert career_sites._is_challenge("", {"cf-mitigated": "challenge"}) is True


@pytest.mark.parametrize("host, blocked", [
    ("velux.wd3.myworkdayjobs.com", False),  # read through its robots-listed sitemaps
    ("wd3.myworkdaysite.com", False),
    ("efzu.fa.em2.oraclecloud.com", True),
    ("careers.publicissapient.com", False),
])
def test_platforms_whose_terms_forbid_automated_access_are_refused(host, blocked):
    assert (career_sites._platform_reservation(host) is not None) is blocked


def test_page_company_falls_back_to_the_hosts_own_label_whatever_the_country():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<html><head></head></html>", "html.parser")
    assert career_sites._page_company(soup, "karrier.acme.hu") == "Acme"
    assert career_sites._page_company(soup, "acme.karrier.hu") == "Acme"
    assert career_sites._page_company(soup, "careers.acme.dk") == "Acme"
    assert career_sites._page_company(soup, "jobs.acme.com") == "Acme"


def test_page_company_strips_a_countrys_tld_from_a_title_tail():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<html><head><title>Állások | Acme.hu</title></head></html>", "html.parser")
    assert career_sites._page_company(soup, "x.example") == "Acme"


def test_company_drops_a_careers_suffix_in_any_language():
    assert career_sites._company({"hiringOrganization": {"name": "Acme Karrier"}}, "x.hu") == "Acme"


def test_company_drops_a_careers_suffix():
    assert career_sites._company({"hiringOrganization": {"name": "Publicis Sapient Careers"}}, "x.dk") == "Publicis Sapient"
    assert career_sites._company({"hiringOrganization": "Acme A/S"}, "x.dk") == "Acme A/S"
    assert career_sites._company({}, "careers.acme.dk") == "careers.acme.dk"


# --- ranking the job URLs before the cap (issue #257) -----------------------

_WX = "https://wd3.myworkdaysite.com/recruiting/velux/Velux_Residential/job"
_PS = "https://careers.publicissapient.com/job-details"
_URLS = {
    "hoersholm": f"{_WX}/dalsvej-99-Hrsholm/Head-of-Data---AI-Platforms_R1070976",
    "german": f"{_WX}/Weidehorst-28/Fachkraft-fr-Lagerlogistik--m-w-d----Standort-Hllhorst_R1070442-1",
    "polish": f"{_WX}/Ul-Kolejowa-7-Gniezno/Technician_R1",
    "copenhagen": f"{_PS}/2026-146394-data-science---manager---retail-copenhagen?trid=abc-copenhagen",
    "chicago": f"{_PS}/2026-173044-senior-associate-chicago?trid=abc",
    "data_elsewhere": f"{_PS}/2026-170457-senior-associate-data-engineering-melbourne?trid=abc",
}
_CONFIG = {"location": "Copenhagen", "role_targets": ["Data Scientist"], "search_keywords": ["Senior Data Engineer", "Machine Learning"]}


def test_urls_naming_the_profile_area_rank_first_in_their_order():
    urls = [_URLS[k] for k in ("german", "chicago", "copenhagen", "polish", "hoersholm")]

    ranked, n = career_sites._rank_urls(urls, {"location": "Copenhagen", "role_targets": ["Chef"]})

    assert ranked == [urls[2], urls[4], urls[0], urls[1], urls[3]]
    assert n == (0, 2, 0, 3)


def test_a_city_of_the_country_counts_as_local_whatever_its_spelling():
    for slug in ("Hrsholm", "Horsholm", "Hoersholm", "kobenhavn", "kbenhavn", "kongens-lyngby", "Denmark", "Aarhus", "arhus"):
        url = f"https://x.com/job/{slug}/Role_R1"
        assert career_sites._rank_urls(["https://x.com/job/Paris/Role_R2", url], {"location": "Copenhagen", "role_targets": ["Chef"]})[0][0] == url, slug


def test_a_content_word_of_the_search_keywords_ranks_a_url_first():
    urls = [_URLS["chicago"], _URLS["data_elsewhere"]]

    ranked, n = career_sites._rank_urls(urls, _CONFIG)

    assert ranked == [urls[1], urls[0]] and n == (0, 0, 1, 1)


def test_seniority_and_stop_words_are_not_topics():
    config = {"location": "Nowhere", "role_targets": ["Senior Manager of the Lead"]}

    ranked, n = career_sites._rank_urls([_URLS["chicago"], _URLS["polish"]], config)

    assert ranked == [_URLS["chicago"], _URLS["polish"]] and n == (0, 0, 0, 2)  # "senior" in the chicago slug did not count


def test_role_targets_stand_in_when_there_are_no_search_keywords():
    config = {"location": "Nowhere", "role_targets": ["Technician"]}

    assert career_sites._rank_urls([_URLS["chicago"], _URLS["polish"]], config)[0][0] == _URLS["polish"]


def test_a_word_inside_another_word_does_not_match():
    config = {"location": "Nowhere", "role_targets": ["Data"]}
    urls = ["https://x.com/job/metadata-team_R1", "https://x.com/job/data-team_R2"]

    assert career_sites._rank_urls(urls, config)[0] == [urls[1], urls[0]]


def test_the_query_string_is_not_read():
    urls = ["https://x.com/job/a_R1?trid=copenhagen", "https://x.com/job/b_R2"]

    assert career_sites._rank_urls(urls, {"location": "Copenhagen", "role_targets": ["Chef"]}) == (urls, (0, 0, 0, len(urls)))


def test_without_location_or_keywords_the_order_is_kept():
    urls = [_URLS["chicago"], _URLS["copenhagen"]]

    assert career_sites._rank_urls(urls, {}) == (urls, (0, 0, 0, len(urls)))


def test_urls_rank_in_tiers_local_and_on_topic_then_local_then_on_topic_then_rest():
    config = {"location": "Copenhagen", "role_targets": ["Data Scientist"]}
    rest, topic, local, both = "https://x.com/job/paris-chef_R1", "https://x.com/job/data-paris_R2", "https://x.com/job/copenhagen-chef_R3", "https://x.com/job/data-copenhagen_R4"

    assert career_sites._rank_urls([rest, topic, local, both], config) == ([both, local, topic, rest], (1, 1, 1, 1))


def test_html_entities_in_markup_titles_are_decoded():
    assert career_sites._text("Engineering Manager&nbsp;– Corporate Actions&nbsp;") == "Engineering Manager – Corporate Actions"
    assert career_sites._text({"name": "R&amp;D"}) == "R&D"


def test_the_same_job_under_several_locales_is_one_page():
    urls = [
        "https://careers.bcg.com/ca/fr/job/52318/Senior-AI-Tech-Architect-Copenhagen",
        "https://careers.bcg.com/global/en/job/52318/Senior-AI-Tech-Architect-Copenhagen",
        "https://careers.bcg.com/jp/ja/job/52318/Senior-AI-Tech-Architect-Copenhagen",
        "https://careers.bcg.com/global/en/job/52309/Manager-Copenhagen",
        "https://acme.dk/it/engineer", "https://acme.dk/jobs/1",
    ]
    assert career_sites._dedupe_locales(urls) == [
        "https://careers.bcg.com/global/en/job/52318/Senior-AI-Tech-Architect-Copenhagen",
        "https://careers.bcg.com/global/en/job/52309/Manager-Copenhagen",
        "https://acme.dk/it/engineer", "https://acme.dk/jobs/1",
    ]


def test_a_url_without_a_twin_in_another_locale_is_left_alone():
    urls = ["https://x.dk/da/job/1", "https://x.dk/da/job/2"]
    assert career_sites._dedupe_locales(urls) == urls

# --- feed detection (issue #282) ---

def _d(det):
    return None if det is None else (det.platform, det.entry)


def test_detect_url_reads_a_workday_tenant():
    assert _d(career_sites.detect_url("https://velux.wd3.myworkdayjobs.com/en-US/Velux_Commercial/job/x")) == (
        "career_sites", "https://velux.wd3.myworkdayjobs.com")
    # the shared host is rewritten to the tenant's own, whose robots.txt lists the sitemaps
    assert _d(career_sites.detect_url("https://wd3.myworkdaysite.com/recruiting/velux/Velux_Commercial/job/x")) == (
        "career_sites", "https://velux.wd3.myworkdayjobs.com")
    assert career_sites.detect_url("https://wd3.myworkdaysite.com/other/velux/x") is None
    assert career_sites.detect_url("https://acme.dk/careers") is None
    assert career_sites.feed_url("https://acme.dk") is None


@pytest.mark.parametrize("target, expected", [
    ("veo.talentbrew.com", ("career_sites", "https://careers.veo.co")),
    ("veo.icims.com", ("career_sites", "https://careers.veo.co")),
    ("velux.wd3.myworkdayjobs.com", ("career_sites", "https://velux.wd3.myworkdayjobs.com")),
    ("a.b.wd3.myworkdayjobs.com", None),
    ("acme.github.io", None),
])
def test_detect_cname(target, expected):
    assert _d(career_sites.detect_cname("careers.veo.co", target, "w")) == expected


def test_detect_html_recognises_job_posting_markup():
    ld = '<script type="application/ld+json">{"@type": "JobPosting", "title": "A"}</script>'
    assert _d(career_sites.detect_html(ld, "https://careers.publicissapient.com/job-details/1")) == (
        "career_sites", "https://careers.publicissapient.com")
    assert career_sites.detect_html('{"@type": ["Thing","JobPosting"]}', "https://a.dk/x") is not None
    assert career_sites.detect_html("<p>x</p>", "https://a.dk/x") is None


# --- the followed employer's name, and what makes a text page a job ad (issue #291) ---------------------------

def _html(name: str) -> str:
    return (_FIX / "listing" / f"{name}.html").read_text(encoding="utf-8")


_JOB = {"title": "Data Scientist", "description": "d", "hiringOrganization": {"name": "Legal Entity Kft"}}


def test_a_followed_name_wins_over_the_hiring_organization_and_the_host():
    from datetime import datetime, timezone

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    named = career_sites._to_posting(_JOB, "https://cw.wd1.myworkdayjobs.com/x/job/1", "cw.wd1.myworkdayjobs.com", now, name="Acme")
    plain = career_sites._to_posting(_JOB, "https://cw.wd1.myworkdayjobs.com/x/job/1", "cw.wd1.myworkdayjobs.com", now)
    assert named["company"] == "Acme" and named["id"].startswith("career_sites.")
    assert plain["company"] == "Legal Entity Kft"


def test_a_followed_name_wins_for_a_page_without_markup_and_the_titles_tail_stays_out_of_company():
    from datetime import datetime, timezone

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    url = "https://jobs.altia.example/vacancy/7"
    named = career_sites._text_posting(_html("altia_ad"), url, "jobs.altia.example", now, name="Altia")
    plain = career_sites._text_posting(_html("altia_ad"), url, "jobs.altia.example", now)
    assert named["company"] == "Altia" and named["title"] == "Senior Data Processing Developer"
    assert plain["company"] == "European Agency"  # unchanged without a followed name


def test_a_people_profile_page_is_not_a_job_page_when_job_signals_are_required():
    from datetime import datetime, timezone

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    url = "https://www.zeiss.example/expertise/jane-doe"
    assert career_sites._text_posting(_html("zeiss_profile"), url, "www.zeiss.example", now) is not None  # today's behaviour
    assert career_sites._text_posting(_html("zeiss_profile"), url, "www.zeiss.example", now, require_job_signals=True) is None


def test_a_page_with_an_apply_button_or_a_job_path_has_job_signals():
    from bs4 import BeautifulSoup

    ad = BeautifulSoup(_html("altia_ad"), "html.parser")
    profile = BeautifulSoup(_html("zeiss_profile"), "html.parser")
    assert career_sites._has_job_signals(ad, "https://x.example/expertise/7")        # an "Apply now" link
    assert career_sites._has_job_signals(profile, "https://x.example/jobs/7")        # a job word in the path
    assert not career_sites._has_job_signals(profile, "https://x.example/expertise/jane-doe")


# --- following a Workday link found inside another platform's pages (#438) ---

import responses as _responses  # noqa: E402

_FOLLOW_WD = "https://acme.wd3.myworkdayjobs.com"


def _follow_session():
    from door.scrapers.http_client import PoliteSession

    return PoliteSession(min_delay=0, max_delay=0, timeout=5, max_retries=0)


@pytest.mark.parametrize("url", [
    f"{_FOLLOW_WD}/Acme_Careers/job/Utrecht/Engineer_R1/apply",
    f"{_FOLLOW_WD}/en-US/Acme_Careers/job/Utrecht/Engineer_R1",
    f"{_FOLLOW_WD}/Acme_Careers",
])
@_responses.activate
def test_a_workday_link_with_jobs_is_followed_as_tenant_and_site(url):
    _responses.add(_responses.POST, f"{_FOLLOW_WD}/wday/cxs/acme/Acme_Careers/jobs", json={"total": 7, "jobPostings": []})
    det = career_sites.follow_link(_follow_session(), url)
    assert (det.platform, det.entry) == ("career_sites", f"{_FOLLOW_WD}/Acme_Careers") and "7 jobs" in det.evidence


@_responses.activate
def test_a_workday_link_with_no_public_jobs_is_recognised_but_not_followed():
    _responses.add(_responses.POST, f"{_FOLLOW_WD}/wday/cxs/acme/Acme_Careers/jobs", json={"total": 0, "jobPostings": []})
    _responses.add(_responses.GET, f"{_FOLLOW_WD}/Acme_Careers/siteMap.xml", body="")
    det = career_sites.follow_link(_follow_session(), f"{_FOLLOW_WD}/Acme_Careers/job/x")
    assert det.entry is None and det.refusal == "cant_yet" and "lists no jobs publicly" in det.evidence


def test_a_link_that_is_no_workday_site_is_none():
    assert career_sites.follow_link(_follow_session(), "https://example.com/careers") is None
    assert career_sites.follow_link(_follow_session(), f"{_FOLLOW_WD}/") is None


# --- a Workday tenant named like an employer whose website was found (#566) ---

_EMPLOYER_FX = TESTS_DIR / "fixtures" / "employer_site"
_TELIA_WD = "https://teliacompany.wd3.myworkdayjobs.com"


def _no_tenant(*hosts):
    """A Workday host with no such tenant: its robots.txt answers 422 (as Workday does)."""
    for host in hosts:
        _responses.add(_responses.GET, f"https://{host}/robots.txt", status=422)


@pytest.mark.real_robots
@_responses.activate
def test_a_workday_tenant_named_like_the_employer_is_found_by_its_robots_sitemaps():
    """Telia's Workday tenant: no link on its websites names it (their careers pages are drawn by script), but
    the tenant named like the group answers with its career sites."""
    _responses.add(_responses.GET, f"{_TELIA_WD}/robots.txt",
                   body=(_EMPLOYER_FX / "teliacompany_wd3_robots.txt").read_text(encoding="utf-8"))
    _responses.add(_responses.POST, f"{_TELIA_WD}/wday/cxs/teliacompany/Telia_careers/jobs",
                   body=(_EMPLOYER_FX / "teliacompany_wd3_jobs.json").read_text(encoding="utf-8"))

    det = career_sites.tenant_probe(_follow_session(), "teliacompany")

    assert (det.platform, det.entry) == ("career_sites", f"{_TELIA_WD}/Telia_careers")
    assert "64 jobs" in det.evidence


@pytest.mark.real_robots
@_responses.activate
def test_no_workday_tenant_of_that_name_is_none():
    _no_tenant(*(f"hm.{dc}.myworkdayjobs.com" for dc in career_sites.WORKDAY_DATA_CENTERS))

    assert career_sites.tenant_probe(_follow_session(), "hm") is None
    assert len(_responses.calls) == len(career_sites.WORKDAY_DATA_CENTERS)


@pytest.mark.real_robots
@_responses.activate
def test_a_workday_tenant_whose_sites_list_no_jobs_is_none():
    _responses.add(_responses.GET, f"{_FOLLOW_WD}/robots.txt", body=f"Sitemap: {_FOLLOW_WD}/Acme_Careers/siteMap.xml\n")
    _responses.add(_responses.POST, f"{_FOLLOW_WD}/wday/cxs/acme/Acme_Careers/jobs", json={"total": 0, "jobPostings": []})
    _responses.add(_responses.GET, f"{_FOLLOW_WD}/Acme_Careers/siteMap.xml", body="")
    _no_tenant(*(f"acme.{dc}.myworkdayjobs.com" for dc in career_sites.WORKDAY_DATA_CENTERS if dc != "wd3"))

    assert career_sites.tenant_probe(_follow_session(), "acme") is None


def test_a_slug_that_is_no_tenant_name_is_not_tried():
    assert career_sites.tenant_probe(_follow_session(), "a.b") is None
    assert career_sites.tenant_probe(_follow_session(), "") is None


def test_page_company_names_an_employer_on_a_co_uk_host():
    soup = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    assert career_sites._page_company(soup, "careers.acme.co.uk") == "Acme"
    assert career_sites._page_company(soup, "acme.co.uk") == "Acme"


@pytest.mark.parametrize(
    "host, name",
    [
        ("jobs.acme.ac.uk", "Acme"),
        ("careers.hmrc.gov.uk", "Hmrc"),
        ("jobs.leedsth.nhs.uk", "Leedsth"),
    ],
)
def test_page_company_skips_every_label_of_a_two_label_ending(host, name):
    soup = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    assert career_sites._page_company(soup, host) == name
