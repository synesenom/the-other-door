# Job sites

## Supported countries

| Where | Sites |
|-------|-------|
| **Denmark** | Jobindex, The Hub, EURAXESS (research positions), Globalnyt (development and humanitarian jobs), HR-Manager (the state, regions, municipalities, RUC and ITU) — plus every worldwide site |
| **France** | France Travail (with its partners' ads), Choisir le service public (public-sector jobs), EURAXESS (research positions), and HelloWork to find employers — plus every worldwide site |
| **Hungary** | KÖZSZOLGÁLLÁS (the public sector), EURAXESS (research positions), and profession.hu to find employers — plus every worldwide site |
| **Sweden** | Platsbanken (Arbetsförmedlingen, all of Sweden), EURAXESS (research positions), and Jobbsafari to find employers — plus every worldwide site |
| **United Kingdom** | Reed, jobs.ac.uk (academic and research positions), EURAXESS (research positions), NHS Jobs (the National Health Service) — plus every worldwide site |
| **Any other country** | Worldwide sites only: Workable's job search, ReliefWeb (development and humanitarian jobs) and the per-company feeds (LinkedIn finds employers for them, see below) |

There are two kinds of site. The **boards** (`jobindex`, `thehub`, `euraxess`, `globalnyt`, `jobmaskinen`, `arbetsformedlingen`, `francetravail`, `choisirleservicepublic`, `kozigallas`, `reed`, `jobs_ac_uk`, `nhs_jobs`, `reliefweb` and `workable`'s
cross-company search) search by your keywords and `location`: `search` reads every board
serving your `location`'s country (the table above; outside Denmark, France, Hungary, Sweden and the United Kingdom that is `workable` and `reliefweb`, and
[`follow`](#per-company-feeds) finds the employers' own feeds). The rest are the
**per-company feeds**: `collect` reads the whole careers board of every employer you follow
(`profile/companies.json`). Neither is listed in the config. LinkedIn, profession.hu, Jobbsafari and HelloWork are
not sites but **discovery sources**, read only for which employers hire: see
[Discovery sources](#discovery-sources).

Only ads written in one of your `languages` are kept. The supported languages are
English, Danish, French, Hungarian, Swedish (see [Configuration](configuration.md#keys)), so an ad in Norwegian, Finnish or German is
dropped even when a site above returns it. Supporting another language means adding its
words for the offline filters — see [Adding a site or a country](adding-a-site.md).

The boards search by your keywords and `location`; none needs a list of companies. The
[per-company feeds](#per-company-feeds) below are filled in by `follow` (from the employers
the boards and LinkedIn show), and by you with `companies add`.

Your country's main job boards missing? Adding them is a self-contained contribution: see
[adding-a-site.md](adding-a-site.md).

## All sites

Each site's endpoint, config key, the terms read before it was added and what its
robots.txt says are in its scraper's module docstring, linked from the table. The verdict
is the terms verdict of [How *The other door* fetches](#how-the-other-door-fetches); the discovery sources
are in [Discovery sources](#discovery-sources).

| Site | Countries | Verdict | Checked |
|------|-----------|---------|---------|
| [`jobindex`](../src/door/scrapers/boards/jobindex.py) | Denmark | allowed | 2026-10-11 |
| [`thehub`](../src/door/scrapers/boards/thehub.py) | Denmark | allowed | 2026-10-11 |
| [`euraxess`](../src/door/scrapers/boards/euraxess.py) | Denmark, France, Hungary, Sweden, United Kingdom | allowed | 2026-11-04 |
| [`globalnyt`](../src/door/scrapers/boards/globalnyt.py) | Denmark | allowed | 2026-10-31 |
| [`jobbank`](../src/door/scrapers/boards/jobbank.py) | Denmark | allowed | 2026-10-31 |
| [`jobmaskinen`](../src/door/scrapers/boards/jobmaskinen.py) | Denmark | allowed | 2026-10-31 |
| [`reed`](../src/door/scrapers/boards/reed.py) | United Kingdom | allowed | 2026-11-03 |
| [`jobs_ac_uk`](../src/door/scrapers/boards/jobs_ac_uk.py) | United Kingdom | allowed | 2026-11-03 |
| [`nhs_jobs`](../src/door/scrapers/boards/nhs_jobs.py) | United Kingdom | allowed | 2026-11-03 |
| [`francetravail`](../src/door/scrapers/boards/francetravail.py) | France | allowed | 2026-10-31 |
| [`choisirleservicepublic`](../src/door/scrapers/boards/choisirleservicepublic.py) | France | allowed | 2026-10-31 |
| [`kozigallas`](../src/door/scrapers/boards/kozigallas.py) | Hungary | allowed | 2026-11-12 |
| [`hr_manager`](../src/door/scrapers/feeds/hr_manager.py) | Denmark | allowed | 2026-10-11 |
| [`workable`](../src/door/scrapers/feeds/workable.py) | Any | allowed | 2026-10-11 |
| [`arbetsformedlingen`](../src/door/scrapers/boards/arbetsformedlingen.py) | Sweden | allowed | 2026-10-31 |
| [`reliefweb`](../src/door/scrapers/boards/reliefweb.py) | Any | allowed | 2026-10-31 |
| [`greenhouse`](../src/door/scrapers/feeds/greenhouse.py) | Any | allowed | 2026-10-11 |
| [`lever`](../src/door/scrapers/feeds/lever.py) | Any | allowed | 2026-10-11 |
| [`ashby`](../src/door/scrapers/feeds/ashby.py) | Any | allowed | 2026-10-11 |
| [`recruitee`](../src/door/scrapers/feeds/recruitee.py) | Any | allowed | 2026-10-11 |
| [`pinpoint`](../src/door/scrapers/feeds/pinpoint.py) | Any | allowed | 2026-10-12 |
| [`emply`](../src/door/scrapers/feeds/emply.py) | Denmark | allowed | 2026-10-31 |
| [`varbi`](../src/door/scrapers/feeds/varbi.py) | Sweden | allowed | 2026-10-31 |
| [`visma_recruit`](../src/door/scrapers/feeds/visma_recruit.py) | Sweden | allowed | 2026-11-01 |
| [`talentsoft`](../src/door/scrapers/feeds/talentsoft.py) | France | allowed | 2026-11-01 |
| [`taleez`](../src/door/scrapers/feeds/taleez.py) | France | allowed | 2026-11-01 |
| [`digitalrecruiters`](../src/door/scrapers/feeds/digitalrecruiters.py) | France | allowed | 2026-11-01 |
| [`dayforce`](../src/door/scrapers/feeds/dayforce.py) | Any | allowed | 2026-10-13 |
| [`oracle_hcm`](../src/door/scrapers/feeds/oracle_hcm.py) | Any | allowed | 2026-10-30 |
| [`eploy`](../src/door/scrapers/feeds/eploy.py) | United Kingdom | allowed | 2026-11-04 |
| [`signatur`](../src/door/scrapers/feeds/signatur.py) | Denmark | allowed | 2026-10-13 |
| [`reachmee`](../src/door/scrapers/feeds/reachmee.py) | Sweden | allowed | 2026-10-31 |
| [`recman`](../src/door/scrapers/feeds/recman.py) | Any (Nordic) | allowed | 2026-10-31 |
| [`flatchr`](../src/door/scrapers/feeds/flatchr.py) | France | allowed | 2026-11-01 |
| [`jobtrain`](../src/door/scrapers/feeds/jobtrain.py) | Any (mostly UK) | allowed | 2026-11-04 |
| [`networx`](../src/door/scrapers/feeds/networx.py) | Any (mostly UK) | allowed | 2026-11-04 |
| [`beetween`](../src/door/scrapers/feeds/beetween.py) | France | allowed | 2026-11-01 |
| [`smartrecruiters`](../src/door/scrapers/feeds/smartrecruiters.py) | Any | allowed | 2026-10-13 |
| [`career_sites`](../src/door/scrapers/feeds/career_sites.py) | Any | allowed | 2026-10-11 |
| [`teamtailor`](../src/door/scrapers/feeds/teamtailor.py) | Any | allowed | 2026-10-11 |
| [`personio`](../src/door/scrapers/feeds/personio.py) | Any | allowed | 2026-11-01 |
| [`jobylon`](../src/door/scrapers/feeds/jobylon.py) | Sweden | allowed | 2026-10-31 |
| [`successfactors`](../src/door/scrapers/feeds/successfactors.py) | Any | allowed | 2026-10-11 |

**Development and humanitarian jobs.** `reliefweb` serves the world, so most of its ads are in
other countries. A job is kept when it is in your country, says it is home-based (or remote or
hybrid: "Home-based, Kenya"), or names no country, and dropped when it names only places abroad. A country is recognised as foreign whatever
cities the data lists (every country of the world is in `foreign_places` in
`src/door/i18n/common.toml`), and a bare city with no country beside it is ambiguous and kept.
ReliefWeb's RSS feed returns the 20 newest jobs per keyword and has no paging; its terms allow
copying the materials for personal, non-commercial use only, so *The other door* is for your own search
there. `globalnyt` lists Danish development and humanitarian jobs (a few dozen at a time); it is
read whole, the employer and place from each new ad's page.

Every board of your country is searched; `find --boards a,b` narrows one run.
None needs a login: every request is a logged-out read of a public page or feed, over
plain HTTP. `thehub` is server-rendered: its pages carry the listing in a `window.__NUXT__`
script, which *The other door* runs in a small embedded JavaScript engine (QuickJS, no browser, no
window), so it runs alongside the other boards. Only LinkedIn's employer discovery
([below](#discovery-sources)) reads LinkedIn's logged-out guest endpoints, also over plain HTTP,
so nothing needs a browser.

`jobmaskinen` is the Jobmaskinen hub (job.jobmaskinen.dk), which lists Jobnet's ads without Jobnet's
MitID login (trades, health and public-sector jobs). It searches ad titles by your keywords across
Denmark, reads each new ad's page for its text and date, and finds no terms page to quote (checked
2026-10-31). The ads are Danish. `job.dsr.dk` runs the same plugin over a subset of the hub's ads and
is not read separately.

## How The other door fetches

Every request *The other door* makes, by any scraper, follows the same rules:

- **robots.txt is read for its `Sitemap:` lines** (how `career_sites` finds job pages) and its
  `Crawl-delay`, which is honoured. The discovery sources keep their own, slower pace. Employer feeds are paced 0.2 to 0.5 s per host
  (`FEED_DELAY`), always one request at a time per host, with backoff on 429 and 5xx. No single
  wait is longer than 60 s (`MAX_PAUSE_S`): a `Crawl-delay` or `Retry-After` above it is paced at it.
  `follow` gives each employer's checks 180 s in all (`EMPLOYER_BUDGET_S`); past it the employer is
  an error in the run and the next one goes on.
- **Paced per host.** A server sees only its own traffic, so the pause is a promise to each
  host, not to the run: requests to one host go one at a time, each after its own pause (or
  its `Crawl-delay`, when longer), while requests to different hosts overlap. Sites, and the hosts of a
  per-company feed, are fetched side by side (`scrape_workers`, default 8, `1` = strictly
  one request at a time); employers sharing a provider's domain (every
  `*.teamtailor.com`, `*.myworkdayjobs.com`, `*.recruitee.com`) are fetched at most four at
  a time.
- **Plain HTTP, logged out:** no browser, no CAPTCHA solving, no proxies, no logins.
- **Terms first, one verdict per source.** Every source (a board, an employer-feed platform or a
  discovery source) has a terms verdict, recorded when it is added: `verdict` and `terms_summary` on its
  `Site` (`src/door/core/sites.py`), `VERDICT`, `TERMS_URL` and `TERMS_SUMMARY` in a discovery source's
  module. Its module docstring has a "Terms" passage quoting what the verdict rests on, or saying that no
  terms were found. A test fails for a source without one.

  | Verdict | When | What *The other door* does |
  |---|---|---|
  | `allowed` | The terms allow reading the ads or say nothing against it. "No terms found" and "unclear" are `allowed` too, with the terms (or their absence) quoted in the docstring. | Reads it in a normal run. |
  | `unsure` | The terms do not clearly allow automated reading of the host *The other door* reads. | Reads it only if you turned it on: its own `<source>_discovery` switch, off until you choose, and turning it on shows a notice with the source's terms link. `doctor` and the run summary list the unsure sources that are on. A test refuses an `unsure` board or feed without its own switch. |
  | `reserved` | The terms or the site expressly reserve the content against scraping or text-and-data mining (Danish Copyright Act §11b). | Never reads it: skipped without a request (`reserved` in `find`'s output). None of the current sites is reserved. |

On Jobindex, results are ranked by relevance, not date, 20 to a page. *The other door* turns each search keyword into a phrase of at most two words
and quotes it, so that Jobindex matches the phrase and not each word ("Senior Financial Controller"
and "Lead Financial Controller" both become "financial controller"; "Head of Finance" becomes
"finance"; a field named with "and", "&" or a comma is searched one side at a time,
"monitoring and evaluation" as "monitoring" and "evaluation", because the words are not next to
each other in an ad; a keyword with nothing left once seniority and function words are dropped is
skipped, with a note). It searches the phrase in your area through its path
(`www.jobindex.dk/jobsoegning/storkoebenhavn?q=%22financial+controller%22`). When Jobindex reports more
hits than a page holds, *The other door* reads up to `max_pages_per_keyword` pages (default 3), and
if hits are still left it searches again in every job category
(`www.jobindex.dk/jobsoegning/handel/storkoebenhavn`), and the categories still over a page by the area's
cities and postcode areas, taking turns so that no field gets the searches first (read once per run from
Jobindex's own area sitemap, for Copenhagen only), stopping as soon as the hits are covered or after 120
searches for the phrase. Hits it
could not reach are reported, not treated as a failure, and a run reports how many search
requests it made. The age cutoff is left to `find`. Only an ad whose title shares a word with
your keywords (financial, controller, ...) gets its full text fetched; an ad that leads to an
employer's own page is read from that page. Other ads keep the short search-result text, enough
for the matcher's prescreen to drop them without a request each.

## Universities

Researcher jobs are posted on the universities' own portals and on EURAXESS. What covers each Danish
university (the research-ad side of the issue #431 survey):

| University | How it is covered |
|------------|-------------------|
| DTU | `oracle_hcm` (Oracle Recruiting Cloud, site `CX_1`): `companies add` its vacancies page |
| SDU | `oracle_hcm` (site `CX_1001`): `companies add` its vacancies page |
| Aarhus University | `emply`: its vacancy pages embed Emply's list as a script variable (`DYCON.EmplyData.<id>.vacancies`); `companies add https://international.au.dk/about/profile/vacant-positions/` follows the page. The department is added to the title (`Postdoc in X – Department of Physics and Astronomy`), the ad text is read from the vacancy page, and an ad past its deadline is left out |
| RUC | `hr_manager`, alias `ruc` (`companies add` its feed link; the name `RUC` reaches it when a queued job or your city is in the feed) |
| ITU | `hr_manager`, alias `ituniversitetet`: the vacancy page links its ads by customer number and its job agent as `//delta.hr-manager.net/...?customer=ituniversitetet`, which `companies add` reads |
| University of Copenhagen, CBS | through `euraxess` (CBS also has an HTML list of its own, not read; KU's portal `employment.ku.dk` was not reachable when checked) |
| Aalborg University | through `euraxess` (its own site runs on Varbi with an undocumented JSON list, not read yet) |

`kozigallas` is a board for Hungary's public sector (hospitals and the ambulance service, municipalities, government offices, social care institutes, school districts): the government's public-service job portal KÖZSZOLGÁLLÁS, at `kozszolgallas.ksz.gov.hu` (`kozigallas.gov.hu` redirects there). It posts each keyword to the portal's list endpoint (up to 3 pages of 20 a keyword, newest first) and reads the page of each on-topic new call for its text and place; the ads are Hungarian, and the portal's terms let anyone browse its pages freely. Its certificate chain ends at a root that the bundled certificate list does not carry yet, so the board checks it against the system's trust store, still with full verification.

`euraxess` is a board: it reads the newest EURAXESS offers (up to 10 pages of your country's list, Denmark, France, Hungary, Sweden or the United Kingdom; only the cards whose work country is yours are kept; the
freshness cutoff stops the paging) and keeps those whose title, research field or teaser is on topic for your
keywords. The ranks postdoc, assistant and associate professor, professor, adjunkt and lektor count as one
seniority level, and `keywords` proposes the names of institutes and departments (`Niels Bohr Institute`,
`Institut for Fysik og Astronomi`) as topic terms, since an academic title often names only the rank.

## Per-company feeds

`career_sites`, `greenhouse`, `lever`, `ashby`, `recruitee`, `pinpoint`, `smartrecruiters`, `signatur`, `recman`, `beetween`, `flatchr`, `jobtrain`, `networx`, `dayforce`, `reachmee`, `emply`, `varbi`, `visma_recruit`, `digitalrecruiters`, `taleez`, `talentsoft`, `oracle_hcm`, `eploy`, `teamtailor`, `jobylon`, `personio`, `successfactors`, `hr_manager` and `workable` (with
followed Workable accounts) read the whole careers
board of each company you name, which catches postings a keyword search misses. They are
filled in by `follow`, which finds the feed of every employer the boards and LinkedIn
showed, and by `./door companies add` ([Following companies directly](configuration.md#following-companies-directly)).
Both record each feed in `profile/companies.json`; a followed platform is read by `collect`
without being listed anywhere else, and a platform with no employer followed on it is simply
not read. `init` and `/onboard` don't ask for them. A posting from a feed is new when *The other door*
has not seen it before, whatever its date.

Workable is both: `workable` searches every company hiring through Workable for your
keywords, and for each Workable account you follow it also reads the account whole (every
open job, with its full ad) from the jobs widget Workable's careers pages embed.

`./door companies add <name>` (or "add <company>" in a conversation) finds a company's
feed for you and follows it; `companies` lists whom you follow:
see [Following companies directly](configuration.md#following-companies-directly).

Each feed id can be what you copy from the company's careers page rather than a bare slug;
[Configuration](configuration.md#company-entries) lists the forms each feed accepts.

## Career sites

`career_sites` is the fallback for an employer whose careers page runs on none of the
platforms above. It reads what the site publishes for search engines (Google for Jobs needs
both): the `Sitemap:` lines of its robots.txt (else the sitemap at the site root), preferring sitemaps named
for jobs, then each job page's schema.org `JobPosting` JSON-LD for the title, description,
date, employer and location. Pages new since the last scrape come first (by the sitemap's
`lastmod`, or from the end of a sitemap that has none), but pages whose URL names your area
come first in four tiers: those naming both your area and a topic, then your area only, then a topic
only, then the rest. Your area is your `location`, any city of its country (spelled as a URL spells
it, `Hørsholm` as `Hrsholm`, `horsholm` or `hoersholm`) or the country; a topic is a content word of
your `search_keywords` (`role_targets` without them; seniority and filler words do not count). A site
gets at most 200 pages a run, taken after that ordering, so a worldwide employer's local ads are
not cut off. A page without JobPosting markup is read from its text only when it shows it is a job ad: a
job word in its URL or an "Apply" link or button (a people-profile page is not one). A site whose sitemap has `lastmod` stops early after ten pages in a row older than
the cutoff; one without it (Workday) does not, as its order says nothing about age. Pages *The other door*
has already stored are not fetched again.

Some sites put only a teaser in their markup and load the full ad by JavaScript
(Publicis Sapient does): then the teaser is what *The other door* has. A
page without markup is reported once and skipped. A site that answers with a bot challenge
(Cloudflare, Akamai) is reported as `failed` with "bot protection; not attempted" and left
alone.

**Workday** career sites work this way too: list the tenant's careers URL, e.g.
`https://velux.wd3.myworkdayjobs.com/Velux_Commercial`. A tenant's robots.txt usually lists a sitemap
per career site; one that lists none (Novonesis, Thermo Fisher) names its sites in its `Disallow:`
lines, and *The other door* reads those sites' job lists instead. Every job page carries the
`JobPosting` markup Google for Jobs reads, with the full ad. A Workday sitemap stops at 100 jobs,
so *The other door* also reads the tenant's own job list (`wday/cxs/<tenant>/<site>/jobs` on the tenant's host, the JSON its career
page loads, twenty jobs a request, no search text) and fetches the jobs the sitemap leaves out.
(Workday's own site terms forbid robots on workday.com; the tenant career sites are the employers'.)

**Local jobs only.** A global employer (Cisco, Microsoft, Salesforce) lists thousands of jobs nowhere
near you, and every one costs a page fetch. When your `location` names a country *The other door* has a file
for (`src/door/i18n/country/`), `collect` drops the rest before fetching anything. For Workday, the
first answer of the job list carries its location facets (`locationCountry`, `locationHierarchy1` or
`locations`); *The other door* picks the values naming your country or city (a bare "Remote" stays), asks the list
again with them applied (`appliedFacets`) and reads only those jobs; a tenant with no job in your country
costs one request. Any career-site URL, a sitemap's or a listing's, whose path names another country's
or city's place and none of yours (`Chicago-Illinois` in it yes; `Ballerup-Denmark`,
`Remote-Germany` or no place at all no) is not fetched either; the place names come from
the country files and `foreign_places` in `src/door/i18n/common.toml`. SmartRecruiters postings state their
country, so ones in another country get no detail request. The feeds of followed employers (SuccessFactors, Teamtailor, Greenhouse, Ashby, Lever, Recruitee,
Pinpoint, Workable accounts, HR-Manager, Dayforce, ReachMee, Oracle Cloud HCM) and the JSON-LD ads of career sites are judged by the
location they state: one that names only another country's place or ends in another country's ISO code
(`London, UK`, `Boston, MA`, `Bangalore, Karnataka, IN`) is dropped before it is written; remote,
location-less and multi-location postings with a local place stay (your `remote` setting is not read
here, `match` still applies it). Places a posting names that the country files do not know are kept
and left to `match`. The postings left out are counted per site as
`non_local` in the run record and in `collect`'s summary ("1,200 non-local skipped"); they are not written.
The page caps are unchanged. Without a known country nothing is filtered.
The Greenhouse board API, the SuccessFactors sitemap and Teamtailor's `jobs.json` have no usable country
filter (the first two ignore the parameters, Teamtailor's is undocumented and returned nothing), so
those feeds are fetched once and the non-local postings dropped afterwards. A career-site ad with no
`jobLocation` is judged by its `applicantLocationRequirements`.

**Sites without a sitemap or markup.** An entry that is a listing page (a URL with a path, such as
`https://bechbruun.com/da/karriere/ledige-stillinger/`) is read through its links: the links below
the page (or beside it with a job word in the path, or on a shared SuccessFactors host with a job id)
are the ads. A site whose sitemap pages never carry `JobPosting` markup (three in a row, none with)
is read the same way, from the page's title and main text. `follow` records such a listing page as
the feed when no platform and no sitemap shows, if the page links three ads or the ad that led there.
A site's locale twins (the same job under two language prefixes) count once, and a sitemap that dates
every page the same day is not taken as dated.

## Following an employer (`follow`)

`follow` reads what an employer's postings show, in this order: the shape of its links (a
Talentech `go.talentech.io` short link is expanded first); an HR-Manager `cid=` customer number,
matched to an already followed alias (no page read) or found through the employer site the ad page
links; the DNS name and careers pages of its site; the likely slugs of its name on each feed. A feed
found by the name alone must hold one of the job titles queued for the employer or a job in your
`location`'s country or city, or it is a namesake's and the employer stays unresolved with that reason.
`companies add NAME` asks the same of a feed found by name (a job in your `location`). Either way a feed
that looks like a platform's demo or sample account (a "(Sample)" or "Copy of ..." title, placeholder
text; `demo_*` in `src/door/i18n/common.toml`), or that lists the same jobs as another name's feed in the
same run, is never followed. A feed whose first read answers a 4xx (an HR-Manager alias that no longer
exists) is unresolved too, with the status in the reason.
One HR-Manager feed serves every state agency: the state's recruiting portal (customer 3010,
`statensrekrutteringsloesning_tr`). It is followed once, as "Statens Rekrutteringsløsning", with the agencies
that led to it in its evidence; each further agency is counted as settled. Its postings keep the hiring
agency's name, and an ad of any agency keeps the portal active.
Job boards and aggregators (`join.com`, Jobylon, studiejobs.dk, `www.greenhouse.com`, ...) are never
an employer's site. HR-ON (`recruit.hr-on.com`, the Dalux and BankInvest embeds) is named but not
followed (`refusal` "must_not"): its lists load from a private API and its robots.txt disallows
everything. Visma Recruit (`recruit.visma.com`, where Swedish municipalities and others take applications; Platsbanken
and Jobbsafari ads link there) is followed through a customer's public job list (checked 2026-11-01): an ad's link
carries only the ad's id, but an employer that shows its list on its own website links the platform's list page
(`/External/OJCustomer3/AssignmentList.aspx?guidExtSoftware=`), which is followed like any feed (`visma_recruit`:
Nässjö kommun and Skurups kommun). From an ad link `follow` reads the ad's public JSON
(`/Services/Public/Apply/GetApplySettings?guidAssignment=`, logged out, one request) for the employer's name and
website, looks for the list link on that website (or, when the ad gives none, on the site the name suggests, and only
a list whose own employer is that name is taken), then reads the website for the platform it uses and tries the name
on the public feeds, as for any queued employer. Employers that keep their own list of ads on their website and send
only the apply link to Visma (Uppsala kommun, Uppvidinge kommun, the regions of Gävleborg, Kronoberg and Västerbotten)
are followed on that list page instead (entry: its address): `collect` reads the page and its paging for the ads, opens
the employer's ad page where the link does not carry the Visma id, and reads each ad from Visma's public ad JSON. They
are `unfollowable` (`refusal` "cant_yet") only when no such page is found from the ad (Karlskrona kommun's website
refuses door). Another name of a followed employer (a hospital of a
region) is added to that employer's `also` names, not listed as a second feed. For an employer
still unresolved by its links and its name's feeds, `follow` looks its name up on **Wikidata** (its public API,
no key or login; at most 60 names a run, each once; a refusal is waited out once, and an employer it could not be asked about is tried again on the next run): "Telia Sverige AB" or "Hilti Svenska Aktiebolag", trimmed
of the legal form and of the words a subsidiary's name ends with, is matched to the organisation of that name,
one in your country first, and its official website and its parent organisation's are read like any careers link,
then the careers hosts of the website's domain (`career.hm.com`), then the Workday tenant named like it
(`teliacompany.wd3.myworkdayjobs.com`, whose robots.txt names its career sites). Large employers usually post
there: H&M on SmartRecruiters (named by the staff sign-in link of `career.hm.com`), Telia on Workday, Hilti on
its own careers site. No search engine is asked. If that finds nothing either, `follow_ai_fallback` (default
on) asks Claude Haiku once where its careers page is; only a feed the checks above confirm is followed
(`found_via` `ai`).

**Oracle Cloud HCM** career sites (`*.oraclecloud.com`, `*.oraclecloud.eu`, `/hcmUI/CandidateExperience/<lang>/sites/<site>`)
are followed through the public REST resources the career page itself calls, logged out and without a token
(`recruitingCEJobRequisitions` for the list, paged by `limit`/`offset`; `recruitingCEJobRequisitionDetails` for
the description of a posting not seen before; `recruitingCESites` to resolve a link into an inactive site to the
host's one active site). The entry is `<host>/<site>` (`ejqi.fa.ocs.oraclecloud.eu/CX_1001`): a host can serve several
employers (the UN agencies share `estm.fa.em2.oraclecloud.com`, one site each), so a link to a site of a shared host
names the employer and an inactive site there is not guessed. The host serves no robots.txt. **Terms**
(<https://www.oracle.com/legal/terms.html>, read 2026-10-30, the page carries no date): "You agree not to use any
robot, spider, scraper or other automated means to access the Site or any Oracle accounts, computer systems or
networks without Oracle's express written permission." Those terms govern Oracle's own site; the candidate
experience is the customer's career site, and the feed read is the one a visitor's browser reads (no login, no
challenge passed). Commercial job-data services read the same resources. The decision to follow an employer on
it is yours and so is the risk (see [LEGAL_DISCLAIMER.md](../LEGAL_DISCLAIMER.md)); `companies remove` stops it.

**Ponty** (`ponty-system.se`, a Swedish recruitment system; Jobbsafari and Platsbanken ads link to
`pnty-apply.ponty-system.se/<customer>?id=<n>`) is recognised but not followed. Checked 2026-10-31: those hosts serve
one application form per ad and no list of a customer's ads (the bare customer path is a configuration error, no
feed, sitemap or API is linked), every page is `noindex, nofollow` and its robots.txt disallows everything. The
employer stays unfollowable with `refusal` "cant_yet" unless the look-through below finds a feed. The apply form
itself does name the employer: its sub-heading is the hiring employer (for a recruitment agency's customer, the
agency's client, not the customer), and a customer posting for itself links its own privacy policy, whose site is the
employer's. `follow` reads that one form (logged out, one request), then the site for the platform it uses, then
tries the name on the public feeds, as for any queued employer.

**Welcome to the Jungle** (`welcometothejungle.com/<lang>/companies/<slug>`, Welcome Kit hosts `<x>.welcomekit.co` and the
`welcomekit.co/api/v1/embed` widget some French employers embed on their own careers page) is recognised and never
followed (`refusal` "must_not", checked 2026-11-01): its [terms](https://www.welcometothejungle.com/en/pages/terms)
ban automated copying, company profiles included, and its pages answer a script with a bot challenge. *The other door*
makes no request to those hosts. The link or the page carrying the widget does name the employer (the company
page's slug, or the employer's own host), so `follow` tries that name on the public feeds, as for any queued employer;
if none is found the employer stays `unfollowable`.

**Jobaffinity** (`jobaffinity.fr`, a French recruitment system by Intuition; public-sector ads multiposted to France
Travail link to `jobaffinity.fr/apply/<token>`) is recognised but not followed. Checked 2026-11-01: that
page is an application form for one ad with no ad text, no JSON-LD and no list of the customer's ads; the documented
REST API needs a customer key, which door never uses, and robots.txt disallows the bots it names. The employer stays
unfollowable with `refusal` "cant_yet" unless the look-through finds a feed: the form's data-protection notice names
the data controller (the employer), and `follow` reads that one form (logged out, one request) and tries the name on
the public feeds.

**Eploy** (eploy.com, a UK applicant tracking system; sites on `<name>web.eploy.net` or the employer's own domain: M Group,
Vitality, Cardiff University, the Alan Turing Institute) is followed through the RSS data feed the platform documents
for job boards, logged out and without a key: `/feeds/datafeed.ashx` lists every open ad with its whole text, places and
posting day in one answer, so the postback-paged list and the ad pages are never opened. The entry is the site's host
(`vitalityweb.eploy.net`, `portal.careers.turing.ac.uk`) or any link on it; `follow` recognises an `eploy.net` link, and
a custom domain by its "Powered by Eploy" footer and vacancy pages. Eploy's [terms of use](https://www.eploy.com/about-eploy/security-compliance/terms-of-use/)
(checked 2026-11-04) have no clause on automated access or copying.

**iCIMS** (`<prefix>-<tenant>.icims.com`: `careers-sisk`, `uscareers-pepsico`, `unitedstates-aon`) is recognised and never
followed (`refusal` "must_not", checked 2026-11-04): the public job list and the ads' JSON-LD are readable logged out, but
iCIMS's [terms of use](https://www.icims.com/legal/terms-of-use/) apply to `www.icims.com` "or its related domains and
subdomains" and bar "any robot, spider or other automatic device, process, or means to access the Website ... including
monitoring or copying", and every hosted portal is such a subdomain. *The other door* makes no request to an iCIMS host.
The portal host does name the employer (`careers-sisk` is Sisk), so `follow` tries that name on the public feeds; a
career host on the employer's own domain that points at a portal by CNAME is read as any career site.

**ReachMee** (Talentech's recruiting system, used by Swedish universities, agencies and municipalities) is followed
through the public job list an employer embeds on its career page, logged out and without a key: the platform's
`customerjs/<installation>-<customer>-<site>.js` script holds the list's `validator` and language, the list
(`web103.reachmee.com/ext/<installation>/<customer>/main?site=<site>&validator=…`) is a server-rendered table, and each
ad not seen before is read from its own page (title, place, reference number, text). The entry is
`<installation>/<customer>/<site>` (`I003/354/5`), read off an apply link (the one Jobbsafari or Platsbanken
carries) or an embed script. A customer that publishes in two languages has two sites (Örebro universitet: 5 in Swedish,
12 in English), each its own entry. The list has no publishing date (its date is the application deadline), so
`posted_at` is empty. ReachMee's older RSS feed needs the customer's name, which an apply link does not give, so a link to it
is known but not followed (`refusal` "cant_yet"). **Terms** (<https://talentech.com/sv/legal/>, read 2026-10-31): nothing on
scraping, robots or automated access; the lists are made to be embedded on the employers' own sites. 

**Phenom** is a front end for another job system. A career host that is a CNAME for `*.phenompeople.net` is looked
through: its search-results page (the locale from where the home page redirects to, else from the sitemap) and, if
needed, one job page carry the apply link of the system behind it, usually a Workday site. That site is followed
(as a `career_sites` entry `https://<tenant>.wdN.myworkdayjobs.com/<Site>`) only when its public job list is not
empty (its own job list's total, else its `siteMap.xml`). Many Phenom customers' Workday sites list nothing
publicly (Genmab's, Thermo Fisher's and Cisco's, checked 2026-10-30), and then the employer stays unfollowable with
`refusal` "cant_yet" and the reason "the Workday site behind it lists no jobs publicly".

An unfollowable employer says why it is not followed in `refusal`: `must_not` (its terms or robots.txt rule
it out: HR-ON) or `cant_yet` (*The other door* has no way in yet: a Phenom front end with no readable system behind it, an
Oracle link that names no career site, a Visma Recruit ad link). `companies list` and `companies why` show it, and so do the tools and the
desktop app.

## When a site changes

Job sites redesign their pages, and a scraper that no longer finds its data would silently
return nothing. Two things catch that:

- **`find`** flags a site that returned no results at all with `⚠` (and `jobs summary`
  lists it), without failing the run.
- **`doctor --probe`** probes every site in your `sites` list: one live request for
  page 1 of the first search keyword (or the first board you configured), run through that
  scraper's `probe()`, shown as a `scraper: <site>` line (a site whose terms reserve it is never probed). The probes make live
  requests, so they can take a while — which is why a plain `doctor`
  stays offline and instant. `doctor --probe --fix` probes once to offer fixes. `✓` means the page still
  has the structure the scraper reads. `≠` (drift) means the request succeeded but that
  structure is gone, which is what a site redesign looks like. `!` (warn) is a site that is
  unreachable, a login or bot wall, or a result count far from your recent `jobs/runs/`
  (none where runs average 3 or more, or over five times the average). On drift or warn the
  raw response is saved to `jobs/drift/<site>/<timestamp>.<ext>`. Neither changes the exit
  code.

When a scraper has drifted, `./door doctor --probe --fix` offers `fix scraper: <site>`
and asks first. On yes it needs a clean git working tree and no `find` in progress, makes a
`fix/scraper-<site>-<date>` branch, and has the headless scraper-fixer agent (`claude -p`,
your plan's quota) patch the scraper test-first with a trimmed fixture. The fix is kept only
if the offline test suite passes and a fresh probe reports the site healthy; it is then
committed, pushed and opened as a pull request with `gh`. Without push access or `gh`, the
local branch and the commands to finish by hand are printed instead. A failed fix is
discarded and your branch left as it was. Check the fixture in the PR before you merge it.

## Discovery sources

| Discovery source | Countries |
|------------------|-----------|
| LinkedIn (`linkedin_discovery`) | Any |
| profession.hu (`profession_discovery`) | Hungary |
| HelloWork (`hellowork_discovery`) | France |
| Jobbsafari (`jobbsafari_discovery`) | Sweden |

Each is off until you turn it on, and turning one on shows a notice with its terms link.

The discovery sources are handled differently from the other sites; none needs a login.
They are **employer discovery** only: *The other door* keeps none of their
ads, only the employers behind them, whose own feeds `follow` finds and `collect` reads. They are
run by the `discover` step (`door.core.discovery_sources`), each with its own key (`linkedin_discovery`,
`profession_discovery`, `hellowork_discovery`, `jobbsafari_discovery`), state, pace and rest.

- **LinkedIn finds employers, not jobs.** A search card has no description, and LinkedIn limits a
  burst of about a hundred requests with HTTP 429, so reading its job descriptions does not scale.
  What it is good for is telling which employers hire for your keywords, and 3 of 4 of its jobs
  link to the employer's own site or job system. So *The other door* reads the **search cards over plain
  HTTP** (no browser, no login): one quoted search per keyword (`"financial controller"`, then
  `"registered nurse"`, …), newest first, the last 7 days at most (since the last discovery when that is
  more recent), each paged (ten cards a page) to its last page, a card older than the cutoff, or
  the request budget (150 a run, 2 to 4 s apart; a keyword the budget did not reach comes first
  next run). One boolean `OR` query is not used: it returns fewer cards than its first keyword
  alone. A first 429 is waited out (90 s) and retried; a second one stops the run and rests
  discovery for a day. It keeps the titles that fit a keyword and groups
  them by employer. It then does not open a job page for each new employer: **`follow` first
  tries the employer by name** (the name probe with its same-name confirmation, then Claude
  Haiku's guess at the careers page). Only an employer follow could not resolve stays queued as
  "waiting for an apply link", and `discover` opens its job page (oldest first, with what budget
  the search left) to read where the apply button leads (`candidate.hr-manager.net/...`,
  `<slug>.teamtailor.com`, `jobs.ashbyhq.com/<slug>`, `careers.<company>.com`, …), on a later
  run. The `companies` detection then finds that employer's own feed (recorded in
  `profile/companies.json`) and, once it is followed, `collect` reads the employer's jobs at
  the source. Every `find` does this by itself: `discover` queues the employers
  (`linkedin_discovery`, off until you turn it on; skipped for a day after LinkedIn refuses) and `follow`
  finds their feeds, each reported as its own step and in the summary line
  (`discover: 14 employers, 12 queued, 6 pages + 2 job pages (8/150 requests, 2-4 s pause, rotate); follow: 12 candidates: 5 followed, …`).
  **Easy Apply jobs (LinkedIn-only, no link to the employer) are not covered.**

- **profession.hu (Hungary) works the same way** (`profession_discovery`, off until you turn it on, only for a profile in Hungary). Its terms ban scraping, so it is not a job source: `discover` reads its search pages logged out (plain HTTP, no cookies, no account) for each keyword of the rotation, up to 3 pages of 20 ads, keeps the employers whose ad title is on topic and queues them with the ad link; no ad is stored, scored or tailored. At most 30 requests a run, 3 to 6 s apart; a 429 or 403 or a redirect to a login page stops the run and rests it for a day (`jobs/discovery/profession.json`).
- **Jobbsafari (Sweden) works the same way** (`jobbsafari_discovery`, off until you turn it on, only for a profile in Sweden). Its terms ban scraping and systematic copying, so it is not a job source: `discover` reads its search pages logged out (plain HTTP, no cookies, no account; the data the page embeds) for each keyword of the rotation, up to 3 pages of 30 ads, keeps the employers whose ad title is on topic and queues them with the link to the employer's own application page (without its tracking query; an ad applied for by email has none), for `follow` to find the employer's feed; no ad text is read, stored, scored or tailored. At most 30 requests a run, 3 to 6 s apart; a 429 or 403 or a redirect to a login page stops the run and rests it for a day (`jobs/discovery/jobbsafari.json`).
- **HelloWork (France) works the same way** (`hellowork_discovery`, off until you turn it on, only for a profile in France). Its terms (CGU art. 8.2) ban scraping, so it is not a job source: `discover` reads its search pages logged out (plain HTTP, no cookies, no account) for each keyword of the rotation, up to 3 pages of 30 ads, keeps the employers whose ad title is on topic and queues them with the ad link; no ad is stored, scored or tailored. At most 30 requests a run, 3 to 6 s apart; a 429 or 403 or a redirect to a login page stops the run and rests it for a day (`jobs/discovery/hellowork.json`).

- **Logged out, always.** No login, no cookies, no saved session, no account: your own
  accounts on these sites are never involved, so they cannot be restricted. LinkedIn is
  read through its public guest job search (the `jobs-guest` pages, shown to anyone not
  signed in).
- **Only employers are kept.** From any of the four sources, the candidates queue
  (`jobs/candidates.json`) keeps an employer's name, its links (the ad's, and the employer's own
  apply link when the source shows one), the titles of its on-topic ads and, for LinkedIn, the
  ids of those cards. The entry leaves the queue once `follow` has recorded the employer (a
  LinkedIn employer it could not find by name waits for its job page to be read), or after
  `max_age_days` without being seen again. No ad text, place or posting date is kept, and the
  source's state (`jobs/discovery/<source>.json`) holds only employer names, your keywords,
  timestamps and request counts.
- **Slow, small, spread out and quick to stop.** LinkedIn: a budget of **150 requests a run**
  (search pages and job pages together) with **2 to 4 seconds between two**, job pages only for employers with an ad title on topic for your keywords.
  Employers already followed, or looked at in the last 90 days, are not fetched again
  (`jobs/discovery/linkedin.json`, copied from the older `jobs/linkedin_discovery.json` on first read). The pace adapts: after a refusal the next run gets half the
  budget and twice the pause (down to 10 requests, up to 4 times the pause), and three runs in a
  row without a refusal step it back up toward the defaults. Every run's observation (time,
  requests made, pause, outcome, and for a refusal after how many requests and seconds the first
  429 came) is kept in the `history` list of `jobs/discovery/linkedin.json` (the last 30), so the
  real limit can be read from it. On a second HTTP
  429 in a row (LinkedIn waits 90 s after the first and retries once; also 999 there), on any other error status after one retry, on a
  redirect to a login or authwall page, or on a captcha-like answer, *The other door* stops for the run,
  keeps what it already fetched and records the error. After a refusal (a rate limit, a block, a
  login wall; not a server error) each source rests for 24 hours: runs in that time skip them without a
  request and say when it will be tried again (a refusal during `find`'s discovery is reported,
  never a failed run). No proxies, no IP rotation, no CAPTCHA solving, no spoofed fingerprints.
- **LinkedIn works in the background.** Taking a few minutes, a full `find` starts
  discover first, on a worker thread, and lets it work while `search`, `follow` and `collect`
  run; its line keeps spinning ("page 3/150 · waiting 3 s"). Nothing is written from that
  thread. When it is over, `find` records what it found and, for the employers it queued after
  `follow` and `collect` had run, does a short **late follow and collect** before `match` (shown
  as `+ late: …` on those two lines and in their summaries). `collect` waits for discover if it is
  still going.

