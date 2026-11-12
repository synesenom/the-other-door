"""The site registry: one entry per job site, shared by the CLI, the `Profile`
schema, `doctor` and the docs tests.

Each site is one module, `src/door/scrapers/<name>.py`, and one `Site` entry
below, which says which countries it serves by ISO 3166 code (each with a
`src/door/i18n/country/<cc>.toml`); a site that serves no country in
particular (a global board searched by `location`, a per-company career feed)
works anywhere. See docs/adding-a-site.md.

A site is a board (searched by the profile's keywords: `search`), a per-company feed
(read for each employer followed in `profile/companies.json`: `collect`), or both
(Workable). Kept in `door.core` (rather than with the commands) so the
pipeline, `doctor` and the CLI share one list without a circular import.
"""

from dataclasses import dataclass, field

VERDICTS = ("allowed", "unsure", "reserved")


@dataclass(frozen=True)
class Site:
    """One job site.

    Attributes:
        name: The name used in `boards`, `--boards` and job ids, and of its
            module under `src/door/scrapers/`.
        label: What a person reads: "via <label>" under a posting in the app.
        countries: The ISO 3166 codes of the countries it serves; empty for
            a site that works in any country.
        board: The site is searched with the profile's keywords (`search`): every
            board of the profile's country is (`boards_for_location`).
        config_key: For per-company feeds, the key under which the engine
            hands the scraper the employers followed on its platform (from
            `profile/companies.json`, see `door.core.companies.feed_config`; the
            the platform's `detect_url` etc. are in its module, see `door.scrapers.sdk`); `collect` skips the site until
            at least one employer is followed on it.
        terms_url: The terms of use read before the site was added (issue
            #226): required, so no site is added without them.
        verdict: The terms verdict, one of `VERDICTS` (docs/job-sites.md, "How The other door
            fetches"). `allowed`: the terms allow reading the ads or say nothing against it ("no terms
            found" and "unclear" are allowed too, said in the module docstring). `unsure`: the terms
            forbid automated access on the host the site reads; it runs only once the user turned it on,
            with the disclaimer (`door.core.disclaimer`). `reserved`: the terms expressly reserve the
            content against scraping or text-and-data mining, which Danish Copyright Act §11b honours
            even when robots.txt is open (BoligPortal v ReData, 2025); `scrape` skips a reserved site
            without a request (outcome `reserved`).
        terms_summary: What those terms say, in one sentence ("no terms found" where there are none);
            the disclaimer quotes it.
        cooldown_hours: After the scraper reports pushback (`record_pushback`:
            a 429, a block, a login wall), the engine skips the site this many
            hours (outcome `resting`) instead of asking again; 0 never rests.
    """

    name: str
    label: str = field(kw_only=True)
    countries: tuple[str, ...] = ()
    board: bool = False
    config_key: str | None = None
    terms_url: str = field(kw_only=True)
    verdict: str = field(kw_only=True)
    terms_summary: str = field(kw_only=True)
    cooldown_hours: int = 0

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"{self.name}: verdict must be one of {VERDICTS}, not {self.verdict!r}")

    @property
    def module(self) -> str:
        """Its dotted module: ``door.scrapers.boards.<name>`` for a keyword board, ``door.scrapers.feeds.<name>``
        for an employer feed platform (Workable, a board with a feed, is a feed). A discovery source is not a site
        (`door.core.discovery_sources`, ``door.scrapers.discovery.<name>``)."""
        if self.board and not self.config_key:
            return f"door.scrapers.boards.{self.name}"
        return f"door.scrapers.feeds.{self.name}"


SITES: dict[str, Site] = {s.name: s for s in [
    Site("jobindex", label="Jobindex", countries=("dk",), board=True, terms_url="https://www.jobindex.dk/betingelser/vis?id=226",
         verdict="allowed", terms_summary="the terms of 10 March 2026 say nothing on automated access"),
    Site("thehub", label="The Hub", countries=("dk",), board=True, terms_url="https://thehub.io/terms",
         verdict="allowed", terms_summary="personal, non-commercial use; nothing on scraping"),
    Site("euraxess", label="EURAXESS", countries=("dk", "hu", "se", "fr", "gb"), board=True, cooldown_hours=24,
         terms_url="https://commission.europa.eu/legal-notice_en",
         verdict="allowed", terms_summary="the Commission's legal notice allows reuse under CC BY 4.0; nothing bans automated reading"),
    # Danish development and humanitarian jobs (#432): a small board, every ad on-sector.
    Site("globalnyt", label="Globalnyt", countries=("dk",), board=True, terms_url="https://globalnyt.dk/",
         verdict="allowed", terms_summary="no terms found"),
    # Akademikernes Jobbank sits behind Cloudflare: a refusal rests the board for a day.
    Site("jobbank", label="Akademikernes Jobbank", countries=("dk",), board=True, cooldown_hours=24,
         terms_url="https://jobbank.dk/brugerbetingelser",
         verdict="allowed", terms_summary="no clause on automated access or text-and-data mining"),
    # Reed: the UK's largest general job board; the search page embeds its results.
    Site("reed", label="Reed", countries=("gb",), board=True, cooldown_hours=24,
         terms_url="https://www.reed.co.uk/policies#termsConditions",
         verdict="allowed", terms_summary="copying for private use only; no clause on bots, scraping or text-and-data mining"),
    # jobs.ac.uk: the UK's academic job board; the search page and each ad's JSON-LD are plain HTML.
    Site("jobs_ac_uk", label="jobs.ac.uk", countries=("gb",), board=True, cooldown_hours=24,
         terms_url="https://www.jobs.ac.uk/legal/terms-and-conditions",
         verdict="allowed", terms_summary="no terms found that ban bots; copying is for personal use"),
    # NHS Jobs: the health service's own board; the search page and each ad are plain HTML (ads under the OGL).
    Site("nhs_jobs", label="NHS Jobs", countries=("gb",), board=True, cooldown_hours=24,
         terms_url="https://api.jobs.nhs.uk/employer/terms-and-conditions",
         verdict="allowed", terms_summary="content is published under the Open Government Licence; nothing on automated access"),
    Site("jobmaskinen", label="Jobmaskinen", countries=("dk",), board=True, terms_url="https://job.jobmaskinen.dk/",
         verdict="allowed", terms_summary="no terms found"),
    # Sweden's public job board, through the open JobSearch API (ads under CC0).
    Site("arbetsformedlingen", label="Platsbanken", countries=("se",), board=True,
         terms_url="https://jobsearch.api.jobtechdev.se/",
         verdict="allowed", terms_summary="ads are licensed CC0 and the API is open data"),
    # France Travail: the public employment service; its search also lists the partner boards' ads.
    Site("francetravail", label="France Travail", countries=("fr",), board=True,
         terms_url="https://www.francetravail.fr/informations/informations-legales-et-conditio/conditions-generales-dutilisatio.html",
         verdict="allowed", terms_summary="offers may be reused for any purpose; no clause on bots or scraping"),
    # The French civil service's job site: ministries, universities, towns and hospitals, many with no feed.
    Site("choisirleservicepublic", label="Choisir le service public", countries=("fr",), board=True,
         terms_url="https://choisirleservicepublic.gouv.fr/mentions-legales/",
         verdict="allowed", terms_summary="content is under the etalab-2.0 licence; no clause on bots or scraping"),
    # Hungary's public-service job portal (#678): hospitals, municipalities, social care, school districts.
    Site("kozigallas", label="KÖZSZOLGÁLLÁS", countries=("hu",), board=True,
         terms_url="https://kozszolgallas.ksz.gov.hu/listarticlebycategory/Jogok",
         verdict="allowed", terms_summary="the pages may be browsed freely; no clause on bots or scraping"),
    Site("hr_manager", label="HR-Manager", countries=("dk",), config_key="hr_manager_aliases",
         terms_url="https://talentech.com/legal",
         verdict="allowed", terms_summary="nothing on its public feeds, which are made to be embedded on other sites"),
    # Any country
    Site("greenhouse", label="Greenhouse", config_key="greenhouse_boards", terms_url="https://www.greenhouse.com/legal",
         verdict="allowed", terms_summary="the job board API is documented as public"),
    Site("lever", label="Lever", config_key="lever_companies", terms_url="https://www.lever.co/legal/terms-of-service",
         verdict="allowed", terms_summary="the postings API is documented as public"),
    # Workable is both: a cross-company keyword search (a board) and, for each employer
    # followed on it, the account's own jobs (a feed).
    Site("workable", label="Workable", board=True, config_key="workable_companies", terms_url="https://www.workable.com/terms",
         verdict="allowed", terms_summary="nothing on scraping; its robots.txt allows the API"),
    # Worldwide: the job board of the UN's humanitarian information service (#432); it keeps local, home-based
    # and country-less jobs.
    Site("reliefweb", label="ReliefWeb", board=True, terms_url="https://reliefweb.int/terms-conditions",
         verdict="allowed", terms_summary="personal, non-commercial use; nothing on automated access"),
    Site("ashby", label="Ashby", config_key="ashby_companies", terms_url="https://www.ashbyhq.com/resources/terms",
         verdict="allowed", terms_summary="the job board API is documented for building your own job board"),
    Site("recruitee", label="Recruitee", config_key="recruitee_companies", terms_url="https://recruitee.com/terms",
         verdict="allowed", terms_summary="nothing on scraping"),
    Site("emply", label="Emply", countries=("dk",), config_key="emply_tenants", terms_url="https://emply.com/terms",
         verdict="allowed", terms_summary="no terms found for the API"),
    Site("varbi", label="Varbi", countries=("se",), config_key="varbi_tenants",
         terms_url="https://www.grade.com/villkor-grade-varbi/",
         verdict="allowed", terms_summary="the terms cover candidate accounts; nothing on reading the public job list"),
    # Visma Recruit's public job lists (#567): a customer is followed by the id its own website's link carries.
    Site("visma_recruit", label="Visma Recruit", countries=("se",), config_key="visma_recruit_companies",
         terms_url="https://recruit.visma.com/Public/Applicant.aspx",
         verdict="allowed", terms_summary="the terms cover applicant accounts; nothing on reading the public job list"),
    Site("talentsoft", label="Talentsoft", countries=("fr",), config_key="talentsoft_hosts",
         terms_url="https://agrica-career.talent-soft.com/",
         verdict="allowed", terms_summary="no terms found that ban reading a public job list"),
    Site("digitalrecruiters", label="Digitalrecruiters", countries=("fr",), config_key="digitalrecruiters_sites",
         terms_url="https://www.cegid.com/fr/mentions-legales/",
         verdict="allowed", terms_summary="no terms found for a tenant's visitors"),
    # Eploy (#603): a UK applicant tracking system; each site's own RSS data feed, on <name>web.eploy.net or the employer's domain.
    Site("eploy", label="Eploy", countries=("gb",), config_key="eploy_hosts",
         terms_url="https://www.eploy.com/about-eploy/security-compliance/terms-of-use/",
         verdict="allowed", terms_summary="the website terms have no clause on automated access"),
    Site("pinpoint", label="Pinpoint", config_key="pinpoint_companies", terms_url="https://www.pinpointhq.com/terms-of-use",
         verdict="allowed", terms_summary="nothing on scraping; the feed is the one the career site loads"),
    Site("oracle_hcm", label="Oracle Cloud HCM", config_key="oracle_hcm_companies", terms_url="https://www.oracle.com/legal/terms.html",
         verdict="allowed", terms_summary="the robot ban covers oracle.com, not the customers' career sites"),
    Site("dayforce", label="Dayforce", config_key="dayforce_companies", terms_url="https://www.dayforce.com/terms",
         verdict="allowed", terms_summary="nothing on scraping or bots"),
    Site("reachmee", label="ReachMee", countries=("se",), config_key="reachmee_companies",
         terms_url="https://talentech.com/sv/legal/",
         verdict="allowed", terms_summary="nothing on scraping; the lists are made to be embedded on employers' sites"),
    Site("signatur", label="Signatur", countries=("dk",), config_key="signatur_companies",
         terms_url="https://portal.signatur.dk/ExtJobs/DefaultHosting/TermsAndConditions.aspx?ClientId=1449",
         verdict="allowed", terms_summary="no terms found on reading the public job list"),
    Site("recman", label="Recman", config_key="recman_companies", terms_url="https://pn.recman.page/user-agreement",
         verdict="allowed", terms_summary="no terms found on reading the public job pages"),
    # France's Beetween: WordPress career sites on <tenant>.nous-recrutons.fr or the employer's own host. The
    # vendor's terms (beetween.com/terms-conditions/) cover its own website; the legal pages read are the
    # customers' (module docstring), none bans reading.
    Site("beetween", label="Beetween", countries=("fr",), config_key="beetween_companies",
         terms_url="https://recrutement.beetween.fr/rgpd/",
         verdict="allowed", terms_summary="the vendor's terms cover its own website; the career sites' legal pages ban nothing"),
    Site("smartrecruiters", label="SmartRecruiters", config_key="smartrecruiters_companies",
         terms_url="https://www.smartrecruiters.com/legal/terms-of-use/",
         verdict="allowed", terms_summary="nothing on scraping; the postings API is public"),
    # Each employer's own site: the terms checked are the employer's, recorded per
    # site by the user; schema.org's page documents the markup read.
    Site("career_sites", label="the employer's site", config_key="career_sites", terms_url="https://schema.org/JobPosting",
         verdict="allowed", terms_summary="each employer's own pages; no terms found that ban reading them"),
    Site("teamtailor", label="Teamtailor", config_key="teamtailor_companies", terms_url="https://www.teamtailor.com/en/terms-and-conditions/",
         verdict="allowed", terms_summary="the feeds are public; nothing on scraping"),
    # Sweden's Jobylon: an employer is followed by its company number and read through its public company widget.
    Site("jobylon", label="Jobylon", countries=("se",), config_key="jobylon_companies",
         terms_url="https://www.jobylon.com/privacy-policy",
         verdict="allowed", terms_summary="no terms found for visitors"),
    # Personio (Germany; customers across Europe): an account is followed through its public XML feed.
    Site("personio", label="Personio", config_key="personio_companies",
         terms_url="https://www.personio.com/privacy-policy/",
         verdict="allowed", terms_summary="no terms found for visitors; the feed is documented for job boards"),
    # France's Taleez: an employer is followed by its tenant slug (`<slug>.taleez.com`), read through its public job list.
    Site("taleez", label="Taleez", countries=("fr",), config_key="taleez_companies",
         terms_url="https://taleez.com/mentions-legales",
         verdict="allowed", terms_summary="no clause on reading public job pages or on bots"),
    # France's Flatchr: an employer is followed by its career-site slug and read through the JSON list the page loads.
    Site("flatchr", label="Flatchr", countries=("fr",), config_key="flatchr_companies", terms_url="https://www.flatchr.io/cgu",
         verdict="allowed", terms_summary="nothing about reading public job lists or bots"),
    # Jobtrain (UK): an employer is followed by its tenant, `www.jobtrain.co.uk/<tenant>` or a career host of its own,
    # and read through the job cards the jobs page loads and each ad's JSON-LD.
    Site("jobtrain", label="Jobtrain", config_key="jobtrain_companies", terms_url="https://jobtrain.co.uk/privacy-policy/",
         verdict="allowed", terms_summary="no terms found that mention scraping or bots"),
    # Networx (UK, by IRIS): a job board shared by many employers; an employer is followed by its client id (`cid` in
    # its advert links) and read through the board's search narrowed to that client.
    Site("networx", label="Networx", config_key="networx_companies",
         terms_url="https://www.iris.co.uk/legal/website-terms-conditions/",
         verdict="allowed", terms_summary="no clause on scraping or bots"),
    Site("successfactors", label="SuccessFactors", config_key="successfactors_companies",
         terms_url="https://www.sap.com/about/legal/terms-of-use.html",
         verdict="allowed", terms_summary="the career site feed is public; nothing on scraping"),
    # LinkedIn, profession.hu, HelloWork and Jobbsafari are not sites: they only discover employers (`discover`,
    # `door.core.discovery_sources`), so they have no entry here.
]}

ALL_SITES = list(SITES)

# Sources a posting can carry that are not sites: the older ads of LinkedIn (it only
# discovers employers now) and a posting added by hand, which has no "via".
_OTHER_SOURCES: dict[str, str | None] = {"linkedin": "LinkedIn", "manual": None}


def source_name(source: str | None) -> str | None:
    """A posting's `source` in words ("SuccessFactors"), or None when there is nothing to name."""
    if source in SITES:
        return SITES[source].label
    return _OTHER_SOURCES.get(source or "")


def sites_for_country(country: str | None) -> list[str]:
    """The sites worth offering someone looking in the country with ISO code
    `country`: the ones serving it plus the ones that work anywhere; only the
    latter when it is unknown (``None``)."""
    return [name for name, site in SITES.items() if not site.countries or country in site.countries]

# The sites `search` can read, in registry order; what `--boards` may name.
BOARDS = [name for name, site in SITES.items() if site.board]


def boards_for_country(country: str | None) -> list[str]:
    """The boards serving the country with ISO code `country`, plus the worldwide ones
    (see `sites_for_country`)."""
    return [name for name in sites_for_country(country) if SITES[name].board]


def boards_for_location(location: str) -> list[str]:
    """The boards `search` reads for a profile in *location*: every board of its country
    (an `i18n/country/` file), or only the worldwide ones when the country is unknown."""
    from door import i18n

    country = i18n.country_for_location(location or "")
    return boards_for_country(country.code.lower() if country is not None else None)


# Per-company feeds: `collect` skips them (outcome `not_configured`) until
# the employer list follows at least one company on the platform.
FEED_SITES = {name: site.config_key for name, site in SITES.items() if site.config_key}
