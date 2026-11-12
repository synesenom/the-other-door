"""`find` as a user in each supported country and ad-language set would run it, offline.

One row per (country, ad languages) in COUNTRIES. A new country's rows go here (see `/dev-add-country`).
The real `boards_for_location`, `follow`, `collect`, the locality, prefilter and language passes run; only the
outside is faked: the boards, the feeds (whose stubs apply `sdk.keep_local` as the real feed scrapers do), one
career site over mocked HTTP, and the scorer.
"""

import json
import re
from datetime import date

import pytest
import responses

from door import i18n
from door.commands import find as find_cmd
from door.core import claude_cli, companies, sites
from door.scrapers import sdk
from door.scrapers.feeds import career_sites
from pipeline_utils import fake_scraper, posting
from profile_utils import write_config

COUNTRIES = {
    "dk-en": {"location": "Copenhagen, Denmark", "languages": ["English"], "capital": "Copenhagen",
              "suburb": "Frederiksberg", "city": "Aarhus", "company": "Acme A/S", "local": "da", "country": "Denmark",
              "boards": ["jobindex", "thehub", "euraxess", "globalnyt", "jobbank", "jobmaskinen", "workable", "reliefweb"], "kept_local_language": False},
    "hu-en": {"location": "Budapest, Hungary", "languages": ["English"], "capital": "Budapest",
              "suburb": "Budaörs", "city": "Debrecen", "company": "Acme Kft.", "local": "hu", "country": "Hungary",
              "boards": ["euraxess", "kozigallas", "workable", "reliefweb"], "kept_local_language": False},
    "hu-en-hu": {"location": "Budapest, Hungary", "languages": ["English", "Hungarian"], "capital": "Budapest",
                 "suburb": "Budaörs", "city": "Debrecen", "company": "Acme Kft.", "local": "hu", "country": "Hungary",
                 "boards": ["euraxess", "kozigallas", "workable", "reliefweb"], "kept_local_language": True},
    "se-en": {"location": "Stockholm, Sweden", "languages": ["English"], "capital": "Stockholm",
              "suburb": "Solna", "city": "Örebro", "company": "Acme AB", "local": "sv", "country": "Sweden",
              "boards": ["euraxess", "arbetsformedlingen", "workable", "reliefweb"], "kept_local_language": False},
    "se-en-sv": {"location": "Stockholm, Sweden", "languages": ["English", "Swedish"], "capital": "Stockholm",
                 "suburb": "Solna", "city": "Örebro", "company": "Acme AB", "local": "sv", "country": "Sweden",
                 "boards": ["euraxess", "arbetsformedlingen", "workable", "reliefweb"], "kept_local_language": True},
    "fr-en": {"location": "Paris, France", "languages": ["English"], "capital": "Paris",
              "suburb": "Boulogne-Billancourt", "city": "Lyon", "company": "Acme SAS", "local": "fr", "country": "France",
              "boards": ["euraxess", "francetravail", "choisirleservicepublic", "workable", "reliefweb"], "kept_local_language": False},
    "fr-en-fr": {"location": "Paris, France", "languages": ["English", "French"], "capital": "Paris",
                 "suburb": "Boulogne-Billancourt", "city": "Lyon", "company": "Acme SAS", "local": "fr", "country": "France",
                 "boards": ["euraxess", "francetravail", "choisirleservicepublic", "workable", "reliefweb"], "kept_local_language": True},
    "gb-en": {"location": "London, United Kingdom", "languages": ["English"], "capital": "London",
              "suburb": "Croydon", "city": "Manchester", "company": "Acme Ltd", "local": None, "country": "United Kingdom",
              "boards": ["euraxess", "reed", "jobs_ac_uk", "nhs_jobs", "workable", "reliefweb"], "kept_local_language": True},
}

_EN = ("We are looking for a data scientist to join our analytics team. You will build and evaluate machine learning "
       "models in Python, work with product managers to turn business questions into experiments, and present the "
       "results to colleagues across the company. We offer a friendly office, flexible hours and a strong team.")
_DA = ("Vi søger en dataanalytiker til vores team. Du kommer til at arbejde med modeller i Python, og du skal sammen "
       "med produktchefer omsætte forretningsspørgsmål til forsøg og fortælle kollegerne om resultaterne. Vi tilbyder "
       "et rart kontor, fleksibel arbejdstid og et stærkt fagligt miljø, hvor du får god plads til at udvikle dig.")
_HU = ("Adatelemzőt keresünk a csapatunkba. Python nyelven fogsz modelleket építeni, a termékmenedzserekkel közösen "
       "üzleti kérdésekből kísérleteket készítesz, és az eredményeket bemutatod a cég munkatársainak. Barátságos "
       "irodát, rugalmas munkaidőt és erős szakmai közösséget kínálunk, ahol bőven van lehetőséged fejlődni.")
_FR = ("Nous recherchons un analyste de données pour rejoindre notre équipe. Vous construirez des modèles en Python, "
       "vous transformerez avec les chefs de produit des questions métier en expériences et vous présenterez les "
       "résultats aux collègues de toute l’entreprise. Nous offrons un bureau agréable, des horaires flexibles.")
_SV = ("Vi söker en dataanalytiker till vårt team. Du kommer att bygga modeller i Python, tillsammans med "
       "produktcheferna översätta affärsfrågor till experiment och presentera resultaten för kollegorna i hela "
       "företaget. Vi erbjuder ett trevligt kontor, flexibla arbetstider och en stark gemenskap där du får gott om "
       "utrymme att utvecklas.")
_DE = ("Wir suchen einen Datenanalysten für unser Team. Sie werden Modelle in Python entwickeln, gemeinsam mit den "
       "Produktmanagern Geschäftsfragen in Experimente übersetzen und die Ergebnisse den Kollegen im ganzen "
       "Unternehmen vorstellen. Wir bieten ein freundliches Büro, flexible Arbeitszeiten und ein starkes Team.")
_LANGS = {"da": _DA, "hu": _HU, "sv": _SV, "fr": _FR}

_LOCAL_TITLES = {"da": "Dataanalytiker", "hu": "Adattudós", "sv": "Dataanalytiker", "fr": "Analyste de données H/F"}
# a title as it is stored: the gender tag of a French title is dropped (`title_tags` in lang/fr.toml)
_STORED_TITLES = {"Analyste de données H/F": "Analyste de données"}

_SITE = "https://careers.example.com"
_ASHBY = "https://jobs.ashbyhq.com/acme/"


def _feed_postings(row):
    """(n, location, description, title) of Acme's feed: local, foreign, remote and location-less ads, in four languages."""
    capital, local = row["capital"], row["local"]
    ads = {
        "capital": (1, capital, _EN, "Data Scientist"),
        "suburb": (2, row["suburb"], _EN + " Hybrid with two days at home.", "Senior Data Scientist"),
        "city": (3, row["city"], _EN + " The team sits in the regional office.", "Junior Data Scientist"),
        "berlin": (4, "Berlin", _EN + " Relocation is paid.", "Lead Data Scientist"),
        "code": (5, "Munich, DE", _EN + " The office is near the station.", "Staff Data Scientist"),
        "remote": (6, "Remote", _EN + " Work from anywhere in the country.", "Remote Data Scientist"),
        "nowhere": (7, "", _EN + " The place is agreed with the team.", "Applied Data Scientist"),
        "german": (9, capital, _DE, "Datenanalyst"),
    }
    if local:  # the United Kingdom has no second language: English is its only one
        ads["local_language"] = (8, capital, _LANGS[local], _LOCAL_TITLES[local])
    return ads


# what each ad of the feed becomes: collected (not counted non-local), left by the prefilter, by the language pass
_FOREIGN = {"berlin", "code"}
_PREFILTER_DROPS = {"city"}


def _requirement_page(country):
    return ('<html><script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "title": f"Platform Data Scientist {country}", "description": _EN + f" ({country})",
        "applicantLocationRequirements": {"@type": "Country", "name": country}, "datePosted": "2026-10-05",
        "hiringOrganization": {"name": "Globex"}}) + "</script></html>")


@pytest.fixture
def no_claude(monkeypatch):
    calls = []

    def refuse(*a, **kw):
        calls.append(a)
        raise AssertionError("no claude call is allowed in an offline end-to-end test")

    monkeypatch.setattr(claude_cli, "run", refuse)
    monkeypatch.setattr(claude_cli, "ask", refuse)
    return calls


def _run(env, monkeypatch, row):
    """Run `find` for *row*; returns (record, boards read, config the ashby feed was given)."""
    write_config(env.profile_dir, {"role_targets": ["data scientist"], "location": row["location"],
                                   "languages": row["languages"], "remote": "no", "translate_titles": False,
                                   "topic_terms": ["data scientist", "dataanalytiker", "adattudós", "datenanalyst", "analyste de données"],
                                   "linkedin_discovery": False})
    items = companies.load(env.profile_dir)
    companies.record(items, "Globex", feed=("career_sites", _SITE), status="followed", found_via="manual")
    companies.save(env.profile_dir, items)
    boards_read = []
    first = row["boards"][0]

    def board(site):
        def scrape(config, **kw):
            boards_read.append(site)
            if site != first:
                return []
            return [posting(1, row["company"], source=site, location=row["capital"], title="Data Scientist Board",
                            url=f"https://example.com/{site}/1", apply_url=_ASHBY + "board")]
        return scrape

    for site in sites.boards_for_location(row["location"]):
        fake_scraper(monkeypatch, site, board(site))

    def ashby(config, **kw):
        raw = [posting(n, row["company"], source="ashby", title=title, location=loc, description=desc,
                       url=f"{_ASHBY}{n}", posted_at="2026-10-05T00:00:00+00:00")
               for n, loc, desc, title in _feed_postings(row).values()]
        return sdk.keep_local(raw, config, "ashby")

    fake_scraper(monkeypatch, "ashby", ashby)
    real_career_sites = career_sites.scrape
    monkeypatch.setattr(career_sites, "scrape", lambda config, **kw: real_career_sites(config, **kw))
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    record = find_cmd._find_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)
    return record, boards_read


def _on_disk(env):
    day = env.jobs_dir / "postings" / date.today().isoformat()
    return {p.stem: json.loads(p.read_text()) for p in day.glob("*/*.json")}


def _mock_career_site(row):
    foreign = "Germany"
    pages = {"R1": foreign, "R2": row["country"]}
    responses.add(responses.GET, f"{_SITE}/robots.txt", body=f"Sitemap: {_SITE}/sitemap.xml\n")
    responses.add(responses.GET, f"{_SITE}/sitemap.xml", body='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                  + "".join(f"<url><loc>{_SITE}/job/{k}</loc></url>" for k in pages) + "</urlset>")
    responses.add_callback(responses.GET, re.compile(re.escape(_SITE) + r"/job/"), callback=lambda r: (
        200, {"Content-Type": "text/html; charset=utf-8"}, _requirement_page(pages[r.url.rsplit("/", 1)[-1]])))


@pytest.mark.real_robots
@pytest.mark.parametrize("name", list(COUNTRIES))
@responses.activate
def test_find_in_each_country_keeps_the_local_ads_in_the_profiles_languages(
        name, env, monkeypatch, scorer, country_boards, no_claude):
    row = COUNTRIES[name]
    _mock_career_site(row)

    record, boards_read = _run(env, monkeypatch, row)

    assert record["steps"] == ["search", "follow", "collect", "match"] and record["failures"] == []
    # search: exactly the boards serving the country
    assert sorted(boards_read) == sorted(row["boards"]) == sorted(sites.boards_for_location(row["location"]))
    # follow: the employer with a local company form, from a board posting that points at a feed
    followed = {c.name: (c.feed.platform, c.feed.id) for c in companies.load(env.profile_dir)}
    assert followed[row["company"]] == ("ashby", "acme") and followed["Globex"] == ("career_sites", _SITE)
    # collect: foreign ads never reach disk and are counted
    assert record["collect"]["non_local"] == len(_FOREIGN) + 1
    ads = _on_disk(env)
    feed = {key: _STORED_TITLES.get(ad[3], ad[3]) for key, ad in _feed_postings(row).items()}  # key -> stored title
    ashby_titles = {a["title"] for a in ads.values() if a["source"] == "ashby"}
    assert ashby_titles == {t for k, t in feed.items() if k not in _FOREIGN}
    career = [a for a in ads.values() if a["source"] == "career_sites"]
    career_title = f"Platform Data Scientist {row['country']}"
    assert [a["title"] for a in career] == [career_title]
    # language and prefilter passes
    by_title = {a["title"]: a for a in ads.values()}
    dropped = {t: a["score_reason"] for t, a in by_title.items() if a.get("score") == 0.0}
    expected = {feed[k]: "excluded" for k in _PREFILTER_DROPS}
    expected[career_title] = "excluded"  # the ad names the country, not the profile's city
    expected[feed["german"]] = f"language: {i18n.language_label('de')} not in languages"
    if row["local"] and not row["kept_local_language"]:
        expected[feed["local_language"]] = f"language: {i18n.language_label(row['local'])} not in languages"
    assert dropped == expected
    survivors = {a["id"] for a in ads.values() if a.get("score") != 0.0}
    assert {a["title"] for a in ads.values() if a["id"] in survivors} >= {
        feed[k] for k in ("capital", "suburb", "remote", "nowhere")}
    # every survivor reached the scorer, and nothing else did
    assert sorted(scorer) == sorted(survivors) and record["match"]["scored"] == len(survivors)
    assert no_claude == []


def test_the_rows_are_the_three_profiles_of_the_issue():
    assert list(COUNTRIES) == ["dk-en", "hu-en", "hu-en-hu", "se-en", "se-en-sv", "fr-en", "fr-en-fr", "gb-en"]
