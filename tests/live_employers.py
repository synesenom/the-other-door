"""The real employers the live tests find feeds for (#19), in one place.

Not a test module itself (no `test_` prefix). Each feed platform's live test (`test_<platform>_live.py`,
`test_<platform>_detection_live`) runs the detection `companies add` runs (`companies._resolve_core`) on its row's
careers page: the page still shows the platform, and the feed it names still answers. `tests/core/test_wikidata_live.py`
looks each `BY_NAME` employer up on Wikidata, by the name a job board gives it, and follows its website to its feed
(`companies._by_website`). When an employer moves to another platform or its page moves, change its row here.

`tests/scrapers/test_live_modes_unit.py` fails until every platform in `ats_detect.PRECEDENCE` has a row here (or a
reason in `NO_DETECTION`) and a detection test.
"""

from typing import NamedTuple


class Careers(NamedTuple):
    page: str          # the employer's careers page: its own site, or the one it has on the platform
    location: str      # the profile's location the detection runs for
    platform: str      # what the page resolves to (a look-through platform resolves to the one it hides)
    entry: str | None  # the feed entry it names; None for a platform The other door does not follow


# Feed platform -> a real, stable employer's careers page and what detection finds there.
DETECTION: dict[str, Careers] = {
    "greenhouse": Careers("https://careers.airbnb.com/", "London", "greenhouse", "airbnb"),
    "lever": Careers("https://www.palantir.com/careers/", "London", "lever", "palantir"),
    "ashby": Careers("https://www.pleo.io/en/careers", "Copenhagen", "ashby", "pleo"),
    "recruitee": Careers("https://famly.co/about/careers", "Copenhagen", "recruitee", "famly"),
    "pinpoint": Careers("https://factbird.pinpointhq.com/", "Copenhagen", "pinpoint", "factbird"),
    "teamtailor": Careers("https://www.templafy.com/careers/", "Copenhagen", "teamtailor", "templafy"),
    "jobylon": Careers("https://cdn.jobylon.com/jobs/companies/2420/embed/v2/", "Stockholm", "jobylon", "2420"),
    "workable": Careers("https://dreamdata.io/careers", "Copenhagen", "workable", "dreamdata"),
    "hr_manager": Careers("https://hk.dk/job", "Copenhagen", "hr_manager", "hkdanmark"),
    "hr_on": Careers("https://www.dalux.com/careers/", "Copenhagen", "hr_on", None),
    "visma_recruit": Careers("https://www.nassjo.se/", "Stockholm", "visma_recruit", "f636d73d-8356-43c6-99bd-ba01addf1b55"),
    "successfactors": Careers("https://careers.novonordisk.com", "Copenhagen", "successfactors", "careers.novonordisk.com"),
    "emply": Careers("https://international.au.dk/about/profile/vacant-positions/", "Aarhus", "emply",
                     "https://international.au.dk/about/profile/vacant-positions/"),
    "recman": Careers("https://stillinger.signo.no", "Oslo", "recman", "stillinger.signo.no"),
    "beetween": Careers("https://giboire.nous-recrutons.fr", "Paris", "beetween", "giboire"),
    "digitalrecruiters": Careers("https://recrutement.franprix.fr", "Paris", "digitalrecruiters", "recrutement.franprix.fr"),
    "jobtrain": Careers("https://jobs.crisis.org.uk", "London", "jobtrain", "jobs.crisis.org.uk"),
    "networx": Careers("https://www.current-vacancies.com/Website/Search?SelectedEmployers=3509", "London", "networx", "3509"),
    "eploy": Careers("https://vitalityweb.eploy.net/", "London", "eploy", "vitalityweb.eploy.net"),
    "icims": Careers("https://careers-sisk.icims.com/jobs/search?ss=1", "London", "icims", None),
    "career_sites": Careers("https://careers.maersk.com/", "Copenhagen", "career_sites", "https://www.maersk.com/careers/"),
    "oracle_hcm": Careers("https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1001", "London",
                          "oracle_hcm", "ejqi.fa.ocs.oraclecloud.eu/CX_1001"),
    # Phenom hides a Workday site: Genmab's Phenom pages lead to its Workday tenant.
    "phenom": Careers("https://careers.genmab.com/", "Copenhagen", "career_sites", "https://genmab.wd3.myworkdayjobs.com"),
    "smartrecruiters": Careers("https://careers.smartrecruiters.com/interikeagroup", "Stockholm", "smartrecruiters",
                               "interikeagroup"),
    "signatur": Careers("https://portal.signatur.dk/Pages/Search.aspx?ClientId=2296", "Copenhagen", "signatur", "2296"),
    "dayforce": Careers("https://jobs.dayforcehcm.com/en-US/natus/CANDIDATEPORTALSENSORY", "London", "dayforce",
                        "natus/CANDIDATEPORTALSENSORY"),
    "varbi": Careers("https://www.su.se/english/about-the-university/work-at-su/available-jobs", "Stockholm", "varbi", "su"),
    "reachmee": Careers("https://web103.reachmee.com/ext/I003/354/main?site=5&validator=x&lang=SE", "Stockholm",
                        "reachmee", "I003/354/5"),
    "flatchr": Careers("https://careers.flatchr.io/company/flatchr", "Paris", "flatchr", "flatchr"),
    "talentsoft": Careers("https://agrica-career.talent-soft.com", "Paris", "talentsoft", "agrica-career.talent-soft.com"),
    "personio": Careers("https://pno-group-europe.jobs.personio.de", "Copenhagen", "personio", "pno-group-europe.jobs.personio.de"),
    "taleez": Careers("https://www.donecle.com/careers", "Paris", "taleez", "donecle"),
    "welcometothejungle": Careers("https://www.welcometothejungle.com/fr/companies/doctolib", "Paris", "welcometothejungle", None),
    "jobaffinity": Careers("https://jobaffinity.fr/apply/wqrlmvgzpyc67d0izf", "Paris", "jobaffinity", None),
}

# Platforms with no detection row, and why.
NO_DETECTION: dict[str, str] = {
    "ponty": "an apply link lives only as long as its ad: `test_ponty_live.py` finds current ones through Platsbanken",
}


class ByName(NamedTuple):
    name: str          # the employer's name as a job board gives it
    location: str      # the profile's location (the country Wikidata prefers)
    website: str       # a part of the website Wikidata names for it
    platform: str      # the feed its website leads to
    careers: str       # the page on the way to it: when the feed is not found and this page refuses, not reached


# Employers a board names, looked up on Wikidata and followed to their feed through their website (#566).
BY_NAME: list[ByName] = [
    ByName("H & M Hennes & Mauritz Sverige AB", "Stockholm", "hm.com", "smartrecruiters", "https://career.hm.com/"),
    ByName("Telia Sverige AB", "Stockholm", "telia.se", "career_sites", "https://www.teliacompany.com/"),
    ByName("Hilti Svenska Aktiebolag", "Stockholm", "hilti.", "career_sites", "https://careers.hilti.group/en"),
]
