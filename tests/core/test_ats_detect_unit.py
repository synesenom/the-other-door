"""Which feed a company's careers link, DNS name or page belongs to (issue #233). Pure."""

import pytest

from door.core import ats_detect
from paths import TESTS_DIR


def _d(det):
    return None if det is None else (det.platform, det.entry)


@pytest.mark.parametrize("url", [
    "https://www.jobindex.dk/jobannonce/h1673146/", "https://www.linkedin.com/jobs/view/1", "https://acme.dk/careers",
    "https://apply.workable.com/j/497E870DCF", "https://www.teamtailor.com/en/", "", "not a url",
])
def test_from_url_ignores_everything_else(url):
    assert ats_detect.from_url(url) is None


def test_from_cname_asks_every_platform_and_ignores_the_rest():
    assert ats_detect.from_cname("jobs.lego.com", "lego.phenompeople.net").entry is None
    assert _d(ats_detect.from_cname("jobs.velux.com", "velux.wd3.myworkdayjobs.com")) == (
        "career_sites", "https://velux.wd3.myworkdayjobs.com")
    assert ats_detect.from_cname("careers.acme.dk", "acme.github.io") is None


def test_from_html_finds_an_embedded_board():
    html = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=trustpilot"></script>'
    assert _d(ats_detect.from_html(html, "https://careers.trustpilot.com/")) == ("greenhouse", "trustpilot")


def test_from_html_ignores_a_mere_link_to_a_platforms_home_page():
    html = '<a href="https://www.teamtailor.com/">Powered by Teamtailor</a> <a href="https://recruitee.com/">x</a>'
    assert ats_detect.from_html(html, "https://careers.acme.dk/") is None


@pytest.mark.parametrize("name, candidates", [
    ("Novo Nordisk A/S", ["novonordisk", "novo-nordisk"]),  # never just "novo": another company's board
    ("Trustpilot", ["trustpilot"]),
    ("Københavns Lufthavne", ["koebenhavnslufthavne", "koebenhavns-lufthavne", "kobenhavnslufthavne", "kobenhavns-lufthavne"]),
    ("Netcompany Danmark A/S", ["netcompany"]),
    ("  ", []),
])
def test_slug_candidates(name, candidates):
    assert ats_detect.slug_candidates(name) == candidates


def test_slug_candidates_drop_any_countrys_legal_forms_and_names(monkeypatch):
    """The suffixes come from the country files, so a new country's company forms ("Zrt.") and
    names ("Magyarország") leave the slug the way "A/S" and "Danmark" do."""
    from door import i18n

    hu = i18n.CountryPack(code="hu", name="Hungary", names=["Magyarország"], legal_suffixes=["kft.", "zrt.", "nonprofit kft."])
    monkeypatch.setattr(i18n, "countries", lambda: {"hu": hu})
    assert ats_detect.slug_candidates("Wizz Air Hungary Zrt.") == ["wizzair", "wizz-air"]
    assert ats_detect.slug_candidates("Telekom Magyarország Nonprofit Kft.") == ["telekom"]
    assert ats_detect.slug_candidates("Göböly Kft.") == ["goeboely", "goboly"]   # spelled out, and folded


@pytest.mark.parametrize("url", [
    "https://jobs.workable.com/view/abc", "https://www.it-jobbank.dk/jobannonce/1", "https://www.jobunivers.dk/x",
    "https://job.experis.dk/jobs/1", "https://carbontalent.carbondatasolutions.com/jobs/imp-1",
    "https://dk.indeed.com/viewjob?jk=1", "https://www.jobindex.dk/jobannonce/h1/",
])
def test_job_boards_and_recruiters_are_not_an_employers_own_site(url):
    assert ats_detect.is_job_board(url)


def test_every_board_declares_its_own_hosts():
    """A board's ads link to the board, not the employer: each board module names its hosts
    (`JOB_BOARD_HOSTS` / `JOB_BOARD_EXACT`), so a new country's board joins the list with its module."""
    import importlib

    from door.core import sites

    for site in sites.SITES.values():
        if site.board:
            module = importlib.import_module(site.module)
            hosts = (*getattr(module, "JOB_BOARD_HOSTS", ()), *getattr(module, "JOB_BOARD_EXACT", ()))
            assert hosts, f"{site.name} declares no JOB_BOARD_HOSTS"
            host = hosts[0] + "example" if hosts[0].endswith(".") else hosts[0]
            assert ats_detect.is_job_board(f"https://{host}/x"), site.name


@pytest.mark.parametrize("url", ["https://apply.workable.com/acme/", "https://careers.acme.dk/jobs/1"])
def test_an_employers_site_is_not_a_job_board(url):
    assert not ats_detect.is_job_board(url)


# --------------------------------------------------------------------------- #
# career_links
# --------------------------------------------------------------------------- #

def test_career_links_finds_english_anchor_and_resolves_it():
    html = '<a href="/about/careers">Careers</a><a href="/contact">Contact</a>'
    assert ats_detect.career_links(html, "https://famly.co/") == ["https://famly.co/about/careers"]


def test_career_links_reads_danish_anchor_text_and_href():
    html = ('<a href="/om-os">Om os</a><a href="/ledige-stillinger/">Se ledige stillinger</a>'
            '<a href="/job-og-karriere">Mere</a>')
    links = ats_detect.career_links(html, "https://www.bec.dk/")
    assert links == ["https://www.bec.dk/ledige-stillinger/", "https://www.bec.dk/job-og-karriere"]


def test_career_links_ignore_job_boards_social_mailto_and_fragments():
    html = ('<a href="https://www.jobindex.dk/jobs/acme">Jobs</a>'
            '<a href="https://www.linkedin.com/company/acme/jobs">Careers</a>'
            '<a href="mailto:jobs@acme.dk">Jobs</a><a href="#jobs">Jobs</a>'
            '<a href="javascript:void(0)">Careers</a><a href="/karriere">Karriere</a>')
    assert ats_detect.career_links(html, "https://acme.dk/") == ["https://acme.dk/karriere"]


def test_career_links_deduplicate_and_rank_text_before_href_and_own_site_first():
    html = ('<a href="/team/jobs-archive">Archive</a>'
            '<a href="https://other.example/careers">Careers</a>'
            '<a href="/join">Join us</a><a href="/join">Join us again</a>')
    assert ats_detect.career_links(html, "https://acme.com/") == [
        "https://acme.com/join", "https://other.example/careers", "https://acme.com/team/jobs-archive"]


def test_career_links_prefers_a_careers_subdomain_and_caps():
    html = "".join(f'<a href="/careers/{i}">Careers {i}</a>' for i in range(10))
    html += '<a href="https://careers.acme.com/">Careers</a>'
    links = ats_detect.career_links(html, "https://acme.com/", limit=4)
    assert len(links) == 4 and links[0] == "https://careers.acme.com/"


def test_career_links_ignores_unrelated_words_inside_other_words():
    assert ats_detect.career_links('<a href="/jobless-claims">Blog</a>', "https://acme.com/") == []


# --- follow v2: more links, more boards ---------------------------------------

@pytest.mark.parametrize("url", [
    "https://join.com/companies/acme/123-engineer", "https://emp.jobylon.com/jobs/1-x/", "https://www.studiejobs.dk/job/1",
    "https://frivilligjob.dk/job/1", "https://temp-team.dk/job/1", "https://www.greenhouse.com/", "https://apply.careers.microsoft.com/careers/job/1",
    "https://engradar.com/jobs/smartrecruiters:ikea:1", "https://app.jobmatchprofile.com/cfw172/x/y",
])
def test_more_job_boards_and_aggregators_are_not_an_employers_own_site(url):
    assert ats_detect.is_job_board(url)


@pytest.mark.parametrize("url", ["https://boards.greenhouse.io/acme", "https://job-boards.greenhouse.io/acme/jobs/1",
                                 "https://joincompany.dk/jobs", "https://careers.acme.dk/join"])
def test_a_feed_host_or_a_lookalike_is_not_a_job_board(url):
    assert not ats_detect.is_job_board(url)


def test_a_talentech_short_link_is_recognised_and_its_redirect_unwrapped():
    assert ats_detect.is_short_link("https://go.talentech.io/0hiy8")
    assert not ats_detect.is_short_link("https://www.talentech.io/")
    target = ("https://careersites-api.talentech.io/redirect?ats_job_id=170232&tenant_id=3b0a&original_apply_url="
              "https%3A%2F%2Fcandidate.hr-manager.net%2FApplicationInit.aspx%3Fcid%3D3010%26ProjectId%3D170232&utm_medium=x")
    assert ats_detect.unwrap_redirect(target) == \
        "https://candidate.hr-manager.net/ApplicationInit.aspx?cid=3010&ProjectId=170232"
    assert ats_detect.unwrap_redirect("https://example.com/a") is None


def test_an_older_successfactors_career_link_names_its_company_but_has_no_job_list():
    # career2.successfactors.eu lists nothing without a script; the employer's own page must be found
    assert ats_detect.from_url("https://career2.successfactors.eu/career?career_ns=job_listing&company=pfapensionP&career_job_req_id=15636") is None
    assert ats_detect.is_shared_ats_host("https://career2.successfactors.eu/career?company=x")
    assert not ats_detect.is_shared_ats_host("https://careers.acme.dk/")


# --- a careers listing page whose ads are plain links (the career-site fallback) ---------------

_LISTING = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "career_sites" / "listing"


def _listing(name):
    return (_LISTING / f"{name}.html").read_text(encoding="utf-8")


def test_ad_links_are_the_pages_below_a_listing():
    url = "https://bechbruun.com/da/karriere/ledige-stillinger/"
    links = ats_detect.ad_links(_listing("bechbruun_list"), url)
    assert len(links) >= 6
    assert all(l.startswith(url) and l != url for l in links)
    assert "https://bechbruun.com/da/karriere/ledige-stillinger/data-scientist-student/" in links
    # the page's other links (home, about us) are not ads
    assert not any(l.endswith("/om-os/") for l in links)


def test_ad_links_below_a_listing_page_without_a_trailing_slash():
    links = ats_detect.ad_links(_listing("pentia_list"), "https://pentia.dk/service/karriere")
    assert "https://pentia.dk/service/karriere/react-native-technical-lead-odense" in links


def test_ad_links_may_be_siblings_of_the_listing_page_when_the_path_names_a_job():
    url = "https://portal.signatur.dk/ExtJobs/DefaultHosting/JobList.aspx?ClientId=2296"
    links = ats_detect.ad_links(_listing("signatur_list"), url)
    assert len(links) == 6 and all("JobDetails.aspx?ClientId=2296&WebAdId=" in l for l in links)
    assert not any("TermsAndConditions" in l for l in links)


def test_ad_links_may_sit_on_a_shared_ats_host_when_they_carry_a_job_id():
    links = ats_detect.ad_links(_listing("pfa_list"), "https://www.pfa.dk/om-pfa/job-i-pfa/ledige-job/")
    assert len(links) == 3 and all(l.startswith("https://career2.successfactors.eu/career?") for l in links)
    assert not any("graduate" in l for l in links)


def test_a_listing_needs_three_ads_or_the_link_that_led_there():
    page = '<a href="/careers/data-scientist">Data Scientist</a><a href="/careers/about">About</a>'
    url = "https://acme.dk/careers"
    assert ats_detect.listing_detection(page, url) is None
    det = ats_detect.listing_detection(page, url, hint="https://acme.dk/careers/data-scientist?utm_source=linkedin")
    assert _d(det) == ("career_sites", "https://acme.dk/careers")
    assert ats_detect.listing_detection(_listing("bechbruun_list"), "https://bechbruun.com/da/karriere/ledige-stillinger/").entry == \
        "https://bechbruun.com/da/karriere/ledige-stillinger/"


def test_navigation_links_of_a_listing_are_not_ads():
    page = ('<a href="/careers/jobs">All jobs</a><a href="/careers/next">Next</a><a href="/careers/page/2">2</a>'
            '<a href="/careers/jobs">Jobs</a>')
    assert ats_detect.ad_links(page, "https://acme.dk/careers") == []


def test_an_ad_link_must_agree_with_the_listings_query():
    page = ('<a href="JobDetails.aspx?ClientId=2296&WebAdId=1">A</a><a href="JobDetails.aspx?ClientId=9&WebAdId=2">B</a>')
    assert ats_detect.ad_links(page, "https://portal.signatur.dk/ExtJobs/D/JobList.aspx?ClientId=2296") == \
        ["https://portal.signatur.dk/ExtJobs/D/JobDetails.aspx?ClientId=2296&WebAdId=1"]


def test_a_home_page_listing_needs_job_words_in_its_ad_paths():
    page = '<a href="/jobs/9410">Projekteringsleder</a><a href="/register">Opret</a><a href="/login">Log ind</a>'
    assert ats_detect.ad_links(page, "https://job.hansentoft.dk/") == ["https://job.hansentoft.dk/jobs/9410"]


# --- is this feed the employer's? (a name matched a board; its jobs must fit what was queued) -----

def test_places_are_the_profile_location_and_its_country():
    assert {"copenhagen", "denmark", "danmark"} <= set(ats_detect.places_for("Copenhagen"))
    assert "aarhus" in ats_detect.places_for("Aarhus, Denmark")
    assert ats_detect.places_for("") == []


def test_a_feed_with_a_queued_title_is_the_employers():
    items = [{"title": "Senior Data Scientist - Copenhagen", "location": {"name": "London"}}]
    why = ats_detect.feed_confirms(items, ["senior data scientist"], [])
    assert why and "title" in why


def test_titles_match_loosely_but_not_on_a_single_word():
    items = [{"title": "Data Scientist (m/f/d)"}, {"text": "Manager"}]
    assert ats_detect.feed_confirms(items, ["Data Scientist"], [])
    assert ats_detect.feed_confirms(items, ["Product Manager"], []) is None


def test_a_feed_with_a_job_in_the_profiles_place_is_the_employers():
    items = [{"title": "Backend", "location": {"name": "Copenhagen, Denmark"}}]
    why = ats_detect.feed_confirms(items, ["Head of Nothing"], ["copenhagen"])
    assert why and "copenhagen" in why.lower()
    assert ats_detect.feed_confirms([{"title": "Backend", "location": "New York"}], ["Head of Nothing"], ["copenhagen"]) is None


def test_only_location_fields_count_for_a_place():
    items = [{"title": "Copenhagen Projects Lead", "description": "We are in Copenhagen", "location": "Austin"}]
    assert ats_detect.feed_confirms(items, ["Something Else"], ["copenhagen"]) is None


def test_a_place_is_a_whole_word():
    assert ats_detect.feed_confirms([{"title": "A", "location": "Aarhusville, TX"}], ["x"], ["aarhus"]) is None


def test_nothing_queued_confirms_nothing():
    assert ats_detect.feed_confirms([{"title": "Data Scientist"}], [], []) is None


def test_a_home_page_is_a_listing_only_for_the_ad_that_led_there():
    page = "".join(f'<a href="/careers/{i}">Careers {i}</a>' for i in range(20))
    assert ats_detect.listing_detection(page, "https://acme.dk/") is None
    assert ats_detect.listing_detection(page, "https://acme.dk/", hint="https://acme.dk/careers/7?utm=x") is not None


_GOOGLE = 'https://accounts.google.com&quot;,null,[[null,&quot;https://x&quot;]]'


def test_from_url_returns_none_for_a_malformed_link():
    assert ats_detect.from_url(_GOOGLE) is None
    assert ats_detect.from_url("http://[bad.example.com/jobs") is None


def test_parts_and_host_checks_survive_a_malformed_url():
    assert ats_detect.parts("http://[bad")[0] == ""
    assert ats_detect.is_job_board("http://[bad") is False
    assert ats_detect.is_shared_ats_host("http://[bad") is False
    assert ats_detect.is_short_link("http://[bad") is False
    assert ats_detect.unwrap_redirect("http://[bad") is None


def test_from_html_survives_a_malformed_link_and_still_finds_the_board():
    html = f'<script>x = "{_GOOGLE}"</script><a href="https://boards.greenhouse.io/acme">Jobs</a>'
    det = ats_detect.from_html(html, "https://acme.example.com/careers")
    assert det is not None and det.platform == "greenhouse"


def test_html_link_pattern_stops_at_an_encoded_quote_but_keeps_ampersands():
    found = ats_detect._URL_IN_HTML.findall(f"{_GOOGLE} https://a.example.com/x?a=1&amp;b=2")
    assert found[0] == "https://accounts.google.com"
    assert "https://a.example.com/x?a=1&amp;b=2" in found


def test_career_links_and_ad_links_skip_a_malformed_href():
    html = '<a href="http://[bad">Careers</a><a href="/careers">Careers</a>'
    assert ats_detect.career_links(html, "https://acme.example.com/") == ["https://acme.example.com/careers"]
    ats_detect.ad_links('<a href="http://[bad">x</a>', "https://acme.example.com/jobs")


# --------------------------------------------------------------------------- #
# name_key / slug_candidates golden values (#289): recorded keys must never move
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name, key", [
    ("Novo Nordisk A/S", "novonordisk"), ("Ørsted", "oersted"), ("Müller GmbH", "mueller"), ("Acme Kft", "acme"),
    ("the LEGO Group", "thelego"), ("Tryg Forsikring A/S", "trygforsikring"),
    ("Københavns Universitet", "koebenhavnsuniversitet"), ("Példa Kft.", "pelda"), ("Ötvös", "oetvoes"),
])
def test_name_key_is_the_first_slug_and_never_moves(name, key):
    from door.core import companies

    assert ats_detect.slug_candidates(name)[0] == key
    assert companies.name_key(name) == key


@pytest.mark.parametrize("name, slugs", [
    ("Novo Nordisk A/S", ["novonordisk", "novo-nordisk"]),
    ("Ørsted", ["oersted", "orsted"]),
    ("Hørsholm Holding ApS", ["hoersholm", "horsholm"]),
    ("Ötvös", ["oetvoes", "otvos"]),
    ("the LEGO Group", ["thelego", "the-lego"]),
])
def test_slug_candidates_golden(name, slugs):
    assert ats_detect.slug_candidates(name) == slugs


def test_a_countrys_job_boards_are_whole_domains_not_markers(monkeypatch):
    from door import i18n

    zz = i18n.CountryPack(code="zz", name="Zedland", job_boards=["boards.example"])
    monkeypatch.setattr(i18n, "countries", lambda: {"zz": zz})
    assert ats_detect.is_job_board("https://boards.example/job/1")
    assert ats_detect.is_job_board("https://www.boards.example/job/1")
    assert not ats_detect.is_job_board("https://notboards.example/job/1")
    assert not ats_detect.is_job_board("https://careers.acme.dk/jobs/1")


def test_profession_hu_is_a_job_board():
    assert ats_detect.is_job_board("https://www.profession.hu/allas/x")
    assert not ats_detect.is_job_board("https://karrier.acme.hu/allas/1")


# --- a demo or sample account is no employer's feed (#435) ---------------------------------------

_FEEDS = TESTS_DIR / "scrapers" / "feeds" / "fixtures"


def _saved(path: str, key: str) -> list:
    import json

    return json.loads((_FEEDS / path).read_text())[key]


@pytest.mark.parametrize("path, key", [
    ("pinpoint/demo_tenant.json", "data"),         # placeholder text ("Vape tattooed gentrify pug ...")
    ("teamtailor/demo_tenant.json", "items"),      # "Copy of iOS developer"
    ("recruitee/sample_tenant.json", "offers"),    # "Senior Marketer (Sample)"
])
def test_a_saved_demo_tenant_looks_like_a_demo(path, key):
    assert ats_detect.feed_looks_demo(_saved(path, key))


@pytest.mark.parametrize("items", [
    [{"title": "Sample Technician", "location": "Copenhagen"}],
    [{"title": "Copy Editor"}, {"title": "Copywriter", "description": "Write copy of our product pages"}],
    [{"title": "Data Scientist", "description": "Lorem is our sister company"}],
    [],
])
def test_an_ordinary_feed_does_not_look_like_a_demo(items):
    assert ats_detect.feed_looks_demo(items) is None


def test_a_us_only_account_has_no_job_in_a_danish_profiles_places():
    items = _saved("smartrecruiters/unrelated_us_account.json", "content")
    assert ats_detect.feed_looks_demo(items) is None
    assert ats_detect.feed_confirms(items, [], ats_detect.places_for("Copenhagen")) is None


def test_the_same_jobs_give_the_same_fingerprint_whatever_their_ids():
    a = [{"id": 1, "title": "Head of DEI - UK"}, {"id": 2, "title": "Marketing Manager"}, {"id": 3, "title": "Intern"}]
    b = [{"id": 9, "title": "Intern"}, {"id": 8, "title": "Head of DEI - UK"}, {"id": 7, "title": "Marketing Manager"}]
    assert ats_detect.feed_fingerprint(a) == ats_detect.feed_fingerprint(b)
    assert ats_detect.feed_fingerprint(a[:2]) is None        # too few jobs to tell a demo from a coincidence
    assert ats_detect.feed_fingerprint(a) != ats_detect.feed_fingerprint([*a[:2], {"title": "Nurse"}])


def test_from_html_prefers_a_customer_alias_over_a_cid_only_link():
    """ITU (#431): the ads link `cid=119`, the job agent `//delta.hr-manager.net/...?customer=ituniversitetet`."""
    html = (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "hr_manager" / "itu_vacancies.html").read_text(encoding="utf-8")
    det = ats_detect.from_html(html, "https://en.itu.dk/About-ITU/Vacancies")
    assert (det.platform, det.entry) == ("hr_manager", "ituniversitetet")
