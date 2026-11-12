"""Visma Recruit (issues #526, #567): a customer's public job list is followed; an ad link alone is not.

Swedish municipalities, regions and mid-size employers take applications on ``recruit.visma.com``. Platsbanken and
Jobbsafari ads link to one ad there (``/spa/public/apply?guidAssignment=<guid>``), which names the ad and not the
employer's board. A customer that publishes its list on its own website links the platform's list page, and that
page is a public, server-rendered list that needs no login, key or cookie (checked 2026-11-01, logged out):

  GET https://recruit.visma.com/External/OJCustomer3/AssignmentList.aspx?guidExtSoftware=<guid>&currentpage=<n>
      An HTML table of the customer's open ads: a row each with the title, the department, the day it was published
      (only on lists that show it) and the deadline, and a link ``AssignmentView.aspx?GuidExtSoftware=<guid>&guid=
      <ad guid>&locId=<n>``. A page past the end has an empty table, an unknown customer answers 404. The page's
      ``og:title`` names the employer (``Nässjö kommun``).
  GET https://recruit.visma.com/External/OJCustomer3/AssignmentView.aspx?GuidExtSoftware=<guid>&guid=<ad guid>&locId=<n>
      The ad: its text under ``div.mainContent`` (``Om arbetsplatsen``, ``Arbetsuppgifter``, ``Kvalifikationer``, ...)
      and a schema.org ``JobPosting`` (title, ``datePosted``, ``hiringOrganization``, ``jobLocation``). The contact
      persons on the page are not copied.

The ``guidExtSoftware`` is the customer's own id, found nowhere but in the link its website carries (``nassjo.se``
menu: "Lediga jobb"; ``skurup.se``: "Lista med lediga jobb (extern sida)"). Configured by ``visma_recruit_companies``:
that guid, or any link to the list or one of its ads. `detect_html` reads it from a careers page, and `resolve`
looks for it from an ad link: the ad's ``GetApplySettings`` JSON (``/Services/Public/Apply/GetApplySettings?
guidAssignment=<guid>``, the data the apply page shows) names the employer, and the employer's own website, guessed
from the name (``nassjo.se``), is searched for the list link; the list is followed only when its ``og:title`` is the
same employer's name (a namesake's website never is).

Many employers keep their own list of ads on their website and send only the apply link to Visma (Uppsala kommun,
Uppvidinge kommun, the regions of Gävleborg, Kronoberg and Västerbotten; their own servers call the platform's
``Feeds/AssignmentList.ashx?guidGroup=`` with a key no page shows). The second route follows them: the entry is the
address of the employer's list page (``visma_recruit_companies``: ``https://www.regionvasterbotten.se/sok-jobb``),
and `scrape` reads that page and its paging (links with a ``page=`` or ``sida=`` query on the same path) for the ads:
- a link that carries the ad's Visma id (``?itemid=<guid>`` on Region Västerbotten, ``RemoteId=<guid>`` on the
  ``offentligajobb.se`` links of Uppvidinge kommun) names it directly;
- any other link under the list's directory is an ad page of the employer (Uppsala ``/Details/?id=``, Gävleborg
  ``/<number>/``), opened for the ``recruit.visma.com/spa/public/apply?guidAssignment=<guid>`` link it carries (a page
  with none is skipped). Region Gävleborg's robots.txt asks for 30 s between requests, so ad pages are opened for at most
  5 minutes per run, in the list's order (newest first on these sites): an ad past the budget is read once the ads above it
  have closed.
Each ad not in ``known_ids`` is then read from Visma's own public JSON, ``GET /Services/Public/Apply/GetApplySettings?
guidAssignment=<guid>`` (the data the apply page shows its visitors, one request): title, the text sections
(``AboutWorkplace``, ``WorkDescr``, ``Qualifications``, ``AdditionalInfo``), ``Header.Municipality`` and a schema.org
``JobPosting`` (``datePosted``, ``hiringOrganization``). ``AssignmentView.aspx`` cannot be used for these: it needs the
customer's ``guidExtSoftware``, which the ad does not give. The employers' own ad pages carry no JSON-LD, so
``career_sites`` does not cover them. `resolve` finds such a list page from an ad link: from the employer's guessed
website it walks the careers links (two levels, at most 8 pages) for a page whose ads' employer (the JSON's
``hiringOrganization``) is the ad's employer. Region Västerbotten and Region Gävleborg are found this way. Karlskrona
kommun's website answers 403 to door (checked 2026-11-01) and is left to the site; the platform's career sites
(``/spa/<lang>/public/careers/<siteGuid>``) are neither detectable from an ad nor found live.

Terms: the applicant terms of Visma Talent Solutions AB (``https://recruit.visma.com/Public/Applicant.aspx``) cover
accounts, applications and the brand; they say nothing of reading the public job list, which the customers' own
websites link for every visitor. Visma's help centre calls the lists "built and maintained by the client". robots.txt
(read 2026-11-01) disallows everything except ``/``, the apply paths, ``/External/OJCustomer3/AssignmentView.aspx`` and
``/Upload/MediaBank/``: the ad pages are allowed, the list page is not, and robots.txt does not gate door's requests
(`http_client.OBEY_ROBOTS`)."""

import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit, urlparse

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    Detection, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, RobotsBlocked, career_links, followed_name,
    host_of, is_job_board, keep_local, make_job_id, name_key, parts, record_entry_error, record_error, record_pushback,
    report, run_probe, scrape_feeds, unfollowable, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("recruit.visma.com",)

# `companies add` reads the list page of a link on a customer: its title names the employer.
NAME_FROM_PAGE = True

# A link to an ad on it must not decide which platform a page is on: only a list link does (`detect_html`).
LINK_PLATFORMS: tuple[str, ...] = ()

_SITE = "visma_recruit"
_KEY = "visma_recruit_companies"
_BASE = "https://recruit.visma.com"
_LIST_URL = f"{_BASE}/External/OJCustomer3/AssignmentList.aspx"
_VIEW_URL = f"{_BASE}/External/OJCustomer3/AssignmentView.aspx"
_APPLY_URL = f"{_BASE}/spa/public/apply"
_MAX_PAGES = 25
_PUSHBACK = (403, 429)
_GUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_GUID = re.compile(rf"^{_GUID_PATTERN}$")
_LIST_LINK = re.compile(
    rf"recruit\.visma\.com/External/OJCustomer3/Assignment(?:List|View)\.aspx\?(?:[^\"'\s<>]*?[&;?])?guidExtSoftware=({_GUID_PATTERN})",
    re.IGNORECASE)
_REASON = ("Visma Recruit: an ad's link names the ad, not the employer's board, and the employer's job list "
           "(whose id only its own website carries) was not found; not followed")
_LINK = re.compile(r"""https?://recruit\.visma\.com/(?:spa/|Public/|External/)""", re.IGNORECASE)


# --- the list's guid ---

def list_guid(value: str) -> str | None:
    """The customer's ``guidExtSoftware`` (lower case) of an entry: the guid itself, or a link to its list or one
    of its ads; None for anything else. Pure."""
    value = (value or "").strip()
    if _GUID.match(value.lower()):
        return value.lower()
    found = _LIST_LINK.search(value)
    return found.group(1).lower() if found else None


def _list_url(guid: str) -> str:
    return f"{_LIST_URL}?guidExtSoftware={guid}"


# --- parsing (pure) ---

def _clean(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def _date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip()) if value and value.strip() else None
    except ValueError:
        return None


def parse_list(html: str) -> tuple[str, list[dict]]:
    """``(employer name, rows)`` of one page of a customer's list; a row is ``{guid, loc_id, title, department,
    published, deadline}`` (``published`` None when the list has no such column). An empty table is no rows.
    Raises ``ValueError`` when the page is no list (a maintenance page, a block page). Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find("table", id="list")
    if table is None:
        raise ValueError("no job table in Visma Recruit's answer")
    og = soup.find("meta", attrs={"property": "og:title"})
    name = _clean(og.get("content", "")) if og is not None else ""
    if not name and soup.title is not None:
        name = _clean(soup.title.get_text()).rsplit(" - ", 1)[-1]
    heads = [_clean(th.get_text()).lower() for th in table.select("thead th")]
    rows, seen = [], set()
    for tr in table.select("tbody tr"):
        link = tr.find("a", attrs={"data-guid": True})
        cells = tr.find_all("td")
        if link is None or len(cells) < 2:
            continue
        guid = link["data-guid"].strip().lower()
        if guid in seen:
            continue
        seen.add(guid)

        def column(word: str) -> str | None:
            for head, cell in zip(heads, cells):
                if word in head:
                    return _clean(cell.get_text()) or None
            return None

        rows.append({
            "guid": guid, "loc_id": link.get("data-locid") or "1", "title": _clean(link.get_text()),
            "department": _clean(cells[1].get_text()), "published": column("publicerad"),
            "deadline": column("ansök senast"),
        })
    return name, rows


def _schema(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _address(value) -> str:
    """A schema.org ``jobLocation.address``: a string, or an ``addressLocality``, tidied (``"Gatan 1 , Ort "``)."""
    if isinstance(value, dict):
        value = value.get("addressLocality") or value.get("streetAddress") or ""
    return re.sub(r"\s+,", ",", _clean(value)) if isinstance(value, str) else ""


def _description(content) -> str:
    """The ad's text: each ``h2`` heading and paragraph of ``div.mainContent`` on its own lines, without the share
    and apply buttons, the map link and the contact persons."""
    lines: list[str] = []
    for child in content.find_all(recursive=False):
        if child.name == "h2":
            heading = _clean(child.get_text())
            nxt = child.find_next_sibling()
            if nxt is not None and "contacts" in (nxt.get("class") or []):
                continue   # the contact persons are people, not the ad
            if heading:
                lines.append(heading)
        elif child.name == "p":
            for br in child.find_all("br"):
                br.replace_with("\n")
            lines.extend(line for line in (_clean(part) for part in child.get_text().split("\n")) if line)
    return "\n".join(lines)


def parse_detail(html: str) -> dict | None:
    """``{description, location, posted_at, organization}`` of an ad page; None when the page holds no ad.
    The place is the page's ``Kommun`` line, else the schema's ``jobLocation``. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find("div", class_="mainContent")
    schema = _schema(soup)
    if content is None and not schema:
        return None
    location = ""
    for item in soup.find_all(class_="key-information-item"):
        label, value = item.find(class_="label"), item.find(class_="value")
        if label is not None and value is not None and _clean(label.get_text()).lower().startswith("kommun"):
            location = _clean(value.get_text())
    if not location:
        place = schema.get("jobLocation")
        location = _address(place.get("address") if isinstance(place, dict) else place)
    org = schema.get("hiringOrganization")
    description = _description(content) if content is not None else ""
    return {
        "description": description or _clean(schema.get("description") or ""),
        "location": location,
        "posted_at": _date(schema.get("datePosted")),
        "organization": _clean(org.get("name", "")) if isinstance(org, dict) else "",
    }


def _to_posting(row: dict, ad: dict | None, company: str, scraped_at: datetime) -> dict:
    ad = ad or {}
    url = f"{_APPLY_URL}?guidAssignment={row['guid']}"
    posting = JobPosting(
        id=make_job_id(_SITE, row["guid"]),
        title=row["title"],
        company=company or ad.get("organization") or "",
        location=ad.get("location", ""),
        url=url,
        description=ad.get("description", ""),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=row["guid"],
        posted_at=ad.get("posted_at") or _date(row.get("published")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


# --- an employer's own list page (the second route, #567) ---

_ID_KEYS = ("guidassignment", "itemid", "remoteid")   # query keys that carry an ad's Visma id on an employer's links
_PAGE_KEYS = ("page", "sida")
_FILES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".mp4")
_MAX_LIST_PAGES = 10
_MAX_AD_PAGES = 300
_AD_PAGE_BUDGET_S = 300   # a site that asks for 30 s between requests (Region Gävleborg) is read in part per run
_MAX_PROBE_PAGES = 8
_MAX_PROBE_ADS = 4
_SECTIONS = (("Om arbetsplatsen", "AboutWorkplace"), ("Arbetsuppgifter", "WorkDescr"), ("Kompetens", "GeneralCompetence"),
             ("Kvalifikationer", "Qualifications"), ("Övrigt", "AdditionalInfo"), ("Annons", "AdDescription"))


def _norm(url: str) -> str:
    """*url* without its fragment and its default port."""
    parsed = urlsplit(url.strip())
    netloc = parsed.netloc.lower()
    for scheme, port in (("https", ":443"), ("http", ":80")):
        if parsed.scheme == scheme and netloc.endswith(port):
            netloc = netloc[: -len(port)]
    return parsed._replace(netloc=netloc, fragment="").geturl()


def page_entry(value: str) -> str | None:
    """The address of an employer's own list page as an entry (without fragment or default port); None for
    anything that is no web link, or is Visma's or Offentliga jobb's own (a list id, an ad). Pure."""
    value = (value or "").strip()
    if not re.match(r"https?://", value, re.IGNORECASE):
        return None
    host = urlsplit(value).netloc.lower().split(":")[0]
    if not host or any(host == d or host.endswith("." + d) for d in (*PLATFORM_DOMAINS, "offentligajobb.se")):
        return None
    return _norm(value)


def _link_guid(url: str) -> str | None:
    """The Visma id an employer's link to an ad carries (``guidAssignment``, ``itemid``, ``RemoteId``)."""
    for key, values in parse_qs(urlsplit(url).query).items():
        if key.lower() in _ID_KEYS and values and _GUID.match(values[0].strip().lower()):
            return values[0].strip().lower()
    return None


def parse_page(html: str, url: str) -> dict:
    """What an employer's list page links: ``{guids, ads, pages, titles}``. ``guids``: the Visma ids of links that
    carry one; ``ads``: other links under the page's directory (an ad page of the employer; none when the page is
    in the site's root); ``pages``: the page's own paging (same path, a ``page=`` or ``sida=`` query);
    ``titles``: the link texts by guid or ad address. All in order, each once. Pure."""
    base = _norm(url)
    parsed = urlsplit(base)
    directory = parsed.path if parsed.path.endswith("/") else parsed.path.rsplit("/", 1)[0] + "/"
    found: dict = {"guids": [], "ads": [], "pages": [], "titles": {}}
    for a in BeautifulSoup(html or "", "html.parser").find_all("a", href=True):
        target = _norm(urljoin(base, a["href"].strip()))
        link = urlsplit(target)
        if link.scheme not in ("http", "https") or target == base:
            continue
        text = _clean(a.get_text())
        guid = _link_guid(target)
        if guid is not None:
            key, bucket = guid, found["guids"]
        elif link.netloc != parsed.netloc or link.path.lower().endswith(_FILES):
            continue
        elif link.path == parsed.path and any(k.lower() in _PAGE_KEYS for k in parse_qs(link.query)):
            key, bucket = target, found["pages"]
        elif directory != "/" and link.path.startswith(directory) and link.path != parsed.path:
            key, bucket = target, found["ads"]
        else:
            continue
        if key not in bucket:
            bucket.append(key)
            if text:
                found["titles"][key] = text
    return found


def parse_apply_guid(html: str) -> str | None:
    """The Visma id of an employer's ad page: the ``guidAssignment`` of its apply link; None when it has none. Pure."""
    found = re.search(rf"guidAssignment=({_GUID_PATTERN})", html or "", re.IGNORECASE)
    return found.group(1).lower() if found else None


def parse_settings(data) -> dict | None:
    """``{title, description, location, posted_at, organization}`` of an ad's ``GetApplySettings`` JSON; None when
    it holds no ad (a closed one). The text is the ad's sections under their headings; the place is the
    municipality, else the schema's ``jobLocation``. Pure."""
    assignment = data.get("Assignment") if isinstance(data, dict) else None
    if not isinstance(assignment, dict) or not _clean(assignment.get("Title") or ""):
        return None
    try:
        schema = json.loads(data.get("SchemaOrgJson") or "{}")
    except ValueError:
        schema = {}
    schema = schema if isinstance(schema, dict) else {}
    lines: list[str] = []
    for heading, key in _SECTIONS:
        body = [line for line in (_clean(part) for part in str(assignment.get(key) or "").split("\n")) if line]
        if body:
            lines.extend([heading, *body])
    header = data.get("Header") if isinstance(data.get("Header"), dict) else {}
    place = schema.get("jobLocation")
    org = schema.get("hiringOrganization")
    return {
        "title": _clean(assignment["Title"]),
        "description": "\n".join(lines) or _clean(schema.get("description") or ""),
        "location": _clean(header.get("Municipality") or "") or _address(place.get("address") if isinstance(place, dict) else place),
        "posted_at": _date(schema.get("datePosted")),
        "organization": _clean(org.get("name", "")) if isinstance(org, dict) else "",
    }


# --- network ---

def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


def _page(session: PoliteSession, guid: str, number: int) -> str:
    return session.get(_LIST_URL, params={"guidExtSoftware": guid, "currentpage": number},
                       headers={"Accept": "text/html"}).text


def _all_rows(session: PoliteSession, guid: str) -> tuple[str, list[dict]]:
    """The employer's name and every open ad of a list, page by page until one adds none. Raises when the first
    page cannot be read (a pushback is recorded); a later page that fails keeps what was read."""
    name, rows, seen = "", [], set()
    for number in range(1, _MAX_PAGES + 1):
        try:
            found_name, found = parse_list(_page(session, guid, number))
        except (requests.RequestException, RobotsBlocked, ValueError) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
            if number == 1:
                raise
            record_error(_SITE, f"error fetching page {number} of the list {guid}: {exc}")
            break
        name = name or found_name
        fresh = [r for r in found if r["guid"] not in seen]
        if not fresh:
            break
        seen.update(r["guid"] for r in fresh)
        rows.extend(fresh)
    return name, rows


def _list_postings(session: PoliteSession, guid: str, scraped_at: datetime, known_ids: frozenset[str],
                   label: str) -> list[dict]:
    """Every open ad of one customer's list not in *known_ids*, labelled with the followed *label* when given. An
    ad that cannot be read is recorded and skipped; a refusal is pushback and ends the list."""
    name, rows = _all_rows(session, guid)
    todo = [r for r in rows if r["guid"] not in known_ids]
    out: list[dict] = []
    for n, row in enumerate(todo, 1):
        report("detail", n, len(todo))
        try:
            html = session.get(_VIEW_URL, params={"GuidExtSoftware": guid, "guid": row["guid"].upper(), "locId": row["loc_id"]},
                               headers={"Accept": "text/html"}).text
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
                record_entry_error(_SITE, guid, f"{guid!r} refused ad {row['guid']} ({_status(exc)}); stopped", blocked=True)
                break
            record_error(_SITE, f"error fetching ad {row['guid']} of {guid!r}: {exc}")
            continue
        ad = parse_detail(html)
        if ad is None:
            record_error(_SITE, f"ad {row['guid']} of {guid!r} holds no ad")
            continue
        out.append(_to_posting(row, ad, label or name, scraped_at))
    return out


def _settings(session: PoliteSession, guid: str):
    return session.get(_SETTINGS_URL, params={"guidAssignment": guid}, headers={"Accept": "application/json"}).json()


def _page_ads(session: PoliteSession, url: str) -> tuple[dict, list[str]]:
    """The Visma ids an employer's list page shows, with its paging read: ``(found, guids)`` where *found* is the
    last `parse_page` merged with the pages' ``ads``/``titles``. Raises when the first page cannot be read (a
    pushback is recorded); a later page that fails is recorded and skipped."""
    first = _norm(url)
    todo, seen = [first], set()
    merged: dict = {"guids": [], "ads": [], "titles": {}}
    while todo and len(seen) < _MAX_LIST_PAGES:
        page = todo.pop(0)
        if page in seen:
            continue
        seen.add(page)
        try:
            html = session.get(page, headers={"Accept": "text/html"}).text
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
            if page == first:
                raise
            record_error(_SITE, f"error fetching page {page} of the list {first}: {exc}")
            continue
        found = parse_page(html, page)
        for key in ("guids", "ads"):
            merged[key].extend(x for x in found[key] if x not in merged[key])
        merged["titles"].update(found["titles"])
        todo.extend(p for p in found["pages"] if p not in seen)
    return merged, merged["guids"]


def _page_postings(session: PoliteSession, url: str, scraped_at: datetime, known_ids: frozenset[str],
                   label: str) -> list[dict]:
    """Every open ad of one employer's list page not in *known_ids*. A refusal is pushback and ends the list; an ad
    that cannot be read is recorded and skipped, a closed one and an ad page without a Visma link skipped quietly."""
    found, guids = _page_ads(session, url)
    guids = list(guids)
    started = time.monotonic()
    for n, ad_url in enumerate(found["ads"][:_MAX_AD_PAGES]):
        if n and time.monotonic() - started > _AD_PAGE_BUDGET_S:
            report(f"{url}: {len(found['ads']) - n} ad pages left for the next run (time budget)")
            break
        try:
            guid = parse_apply_guid(session.get(ad_url, headers={"Accept": "text/html"}).text)
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
                record_entry_error(_SITE, url, f"{url!r} refused {ad_url} ({_status(exc)}); stopped", blocked=True)
                break
            record_error(_SITE, f"error fetching {ad_url} of {url!r}: {exc}")
            continue
        if guid is not None and guid not in guids:
            guids.append(guid)
    todo = [g for g in guids if g not in known_ids]
    out: list[dict] = []
    for n, guid in enumerate(todo, 1):
        report("detail", n, len(todo))
        try:
            ad = parse_settings(_settings(session, guid))
        except (requests.RequestException, RobotsBlocked, ValueError) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
                record_entry_error(_SITE, url, f"{url!r} refused ad {guid} ({_status(exc)}); stopped", blocked=True)
                break
            record_error(_SITE, f"error fetching ad {guid} of {url!r}: {exc}")
            continue
        if ad is not None:
            out.append(_to_posting({"guid": guid, "title": ad["title"]}, ad, label or ad["organization"], scraped_at))
    return out


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each configured customer list or employer list page. An ad in *known_ids* is not opened."""
    names: dict[str, str] = {}
    for entry in config.get(_KEY) or []:
        key = list_guid(entry) or page_entry(entry)
        if key is not None and key not in names:
            names[key] = followed_name(config, _KEY, entry)

    def fetch(session, key, scraped_at):
        if _GUID.match(key):
            return _list_postings(session, key, scraped_at, known_ids, names[key])
        return _page_postings(session, key, scraped_at, known_ids, names[key])

    return keep_local(scrape_feeds(_SITE, list(names), fetch, group=lambda k: host_of(_BASE if _GUID.match(k) else k),
                                   max_workers=workers(config)), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first configured list or list page (one request); its rows or
    links are the postings, without their text. ``None`` when none is configured."""
    key = next((k for k in (list_guid(e) or page_entry(e) for e in config.get(_KEY) or []) if k), None)
    if key is None:
        return None
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0)
    own = not _GUID.match(key)

    def fetch() -> str:
        return session.get(key, headers={"Accept": "text/html"}).text if own else _page(session, key, 1)

    def parse(text: str):
        scraped_at = datetime.now(timezone.utc)
        if own:
            found = parse_page(text, key)
            rows = [{"guid": g, "title": found["titles"].get(g, "")} for g in found["guids"]]
            rows += [{"guid": parse_qs(urlsplit(a).query).get("id", [a])[0], "title": found["titles"].get(a, "")} for a in found["ads"]]
            if not rows:
                return [], False, "no Visma ads or ad links on the list page"
            return [_to_posting(r, None, "", scraped_at) for r in rows], True, ""
        try:
            name, rows = parse_list(text)
        except ValueError as exc:
            return [], False, str(exc)
        return [_to_posting(row, None, name, scraped_at) for row in rows], True, ""

    return run_probe(fetch, parse, "html")


# --- feed detection (issues #282, #526, #567) ---

def detect_url(url: str) -> Detection | None:
    """A Visma Recruit link: a customer's list (or one of its ads) names the entry to follow; an ad, its apply page
    or a career site names none."""
    host, path, query = parts(url.strip())
    if host != "recruit.visma.com":
        return None
    guid = (query.get("guidextsoftware") or "").strip().lower()
    if _GUID.match(guid) and path and path[-1].lower() in ("assignmentlist.aspx", "assignmentview.aspx"):
        return Detection(_SITE, guid, f"Visma Recruit job list {guid}")
    return unfollowable(_SITE, host, _REASON, "cant_yet")


def detect_html(html: str, url: str) -> Detection | None:
    """A page that links one customer's Visma Recruit list is that customer's (an employer's own site); one that
    links only ads (its own list of ads, each applied for there) is unfollowable."""
    guids = {g.lower() for g in _LIST_LINK.findall(html or "")}
    if len(guids) == 1:
        guid = next(iter(guids))
        return Detection(_SITE, guid, f"{url} links Visma Recruit's job list {guid}")
    if _LINK.search(html or ""):
        return unfollowable(_SITE, f"{url} links to Visma Recruit", _REASON, "cant_yet")
    return None


def feed_url(entry: str) -> str | None:
    """None: the list is HTML, not the JSON list the confirmation reads; the link's guid vouches for it, and
    `alive_url` drops a customer that does not exist."""
    return None


def alive_url(entry: str) -> str:
    """The first read of a list: an unknown customer answers 404, which `companies add` reports."""
    return _list_url(entry) if _GUID.match(entry) else entry


def name_page(entry: str, link: str) -> str:
    """The page that names the employer: the customer's list page, whatever *link* (an ad, titled by the job)."""
    return _list_url(entry) if _GUID.match(entry) else entry


_SETTINGS_URL = f"{_BASE}/Services/Public/Apply/GetApplySettings"


def assignment_guid(url: str) -> str | None:
    """The assignment id (lower case) of an ad link, None for any other link (a career site's)."""
    values = parse_qs(urlparse(url.strip()).query)
    for key, found in values.items():
        if key.lower() == "guidassignment" and found and _GUID.match(found[0].strip().lower()):
            return found[0].strip().lower()
    return None


def _text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _site(value) -> str | None:
    """*value* when it is a web link to an employer's own site: no mail link, no platform or job board host."""
    link = _text(value)
    if link is None or not re.match(r"https?://", link, re.IGNORECASE):
        return None
    host = urlparse(link).netloc.lower()
    if not host or any(host == d or host.endswith("." + d) for d in PLATFORM_DOMAINS) or is_job_board(link):
        return None
    return link


def employer_of(payload) -> tuple[str | None, str | None]:
    """``(name, site)`` of the employer an ad's ``GetApplySettings`` JSON names; None for what it does not give."""
    if not isinstance(payload, dict):
        return None, None
    settings = payload.get("ApplicationSettings") if isinstance(payload.get("ApplicationSettings"), dict) else {}
    assignment = payload.get("Assignment") if isinstance(payload.get("Assignment"), dict) else {}
    try:
        schema = json.loads(payload.get("SchemaOrgJson") or "{}")
    except ValueError:
        schema = {}
    org = schema.get("hiringOrganization") if isinstance(schema, dict) else None
    org = org if isinstance(org, dict) else {}
    read_more = assignment.get("ReadMoreLink") if isinstance(assignment.get("ReadMoreLink"), dict) else {}
    name = _text(settings.get("AccountName")) or _text(org.get("name"))
    site = _site(org.get("sameAs")) or _site(org.get("url")) or _site(read_more.get("Url"))
    return name, site


def _folded(name: str) -> str:
    """*name* as a host label: lower case, accents folded, letters and digits only, ``kommun`` left out."""
    text = unicodedata.normalize("NFKD", name.lower().replace("å", "a").replace("ä", "a").replace("ö", "o"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\bkommun\b", " ", text))


def _site_guesses(name: str) -> list[str]:
    """The websites a Swedish employer's name is likely to have (``Skurups kommun`` → ``skurup.se``): the name
    without ``kommun`` (and without a genitive ``s``) on ``.se``, also with ``kommun`` joined. Pure."""
    stem = _folded(name)
    if not stem:
        return []
    stems = [stem, *([stem[:-1]] if stem.endswith("s") and len(stem) > 4 else [])]
    joined = "kommun" in name.lower()
    hosts = [h for s in stems for h in ([f"{s}.se", f"{s}kommun.se"] if joined else [f"{s}.se"])]
    return [f"https://www.{h}/" for h in dict.fromkeys(hosts)][:4]


def _read(session, url: str) -> tuple[str, str] | None:
    try:
        resp = session.get(url, headers={"Accept": "text/html"})
    except (requests.RequestException, RobotsBlocked):
        return None
    return resp.text, resp.url or url


def _linked_list(session, url: str) -> tuple[str, str] | None:
    """``(guid, page)`` of the one Visma Recruit list a website links, from its start page or the careers pages
    that links to; None when it links none."""
    start = _read(session, url)
    if start is None:
        return None
    pages = [start]
    for html, where in pages:
        guids = {g.lower() for g in _LIST_LINK.findall(html)}
        if len(guids) == 1:
            return next(iter(guids)), where
        if where == start[1]:
            for link in career_links(html, where)[:2]:
                page = _read(session, link)
                if page is not None:
                    pages.append(page)
    return None


def _find_list(session, name: str) -> tuple[str, str] | None:
    """``(guid, page)`` of the job list the employer *name* links from its own website, when the list's employer
    is *name* itself; None otherwise."""
    for site in _site_guesses(name):
        found = _linked_list(session, site)
        if found is None:
            continue
        guid, page = found
        try:
            list_name, _rows = parse_list(_page(session, guid, 1))
        except (requests.RequestException, RobotsBlocked, ValueError):
            continue
        if name_key(list_name) == name_key(name):
            return guid, page
    return None


def _same_employer(session, guid: str, name: str) -> bool:
    try:
        ad = parse_settings(_settings(session, guid))
    except (requests.RequestException, RobotsBlocked, ValueError):
        return False
    return ad is not None and name_key(ad["organization"]) == name_key(name)


def _page_is_the_employers(session, html: str, where: str, name: str) -> bool:
    """Whether the page lists ads of Visma Recruit whose employer is *name*: the ids it links, else those of its
    first ad pages' apply links (the deepest links first: sections of the list lie above its ads), each checked
    against the ad's own JSON."""
    found = parse_page(html, where)
    if any(_same_employer(session, g, name) for g in found["guids"][:3]):
        return True
    ads = sorted(found["ads"], key=lambda u: -urlsplit(u).path.count("/"))
    for ad_url in ads[:_MAX_PROBE_ADS]:
        page = _read(session, ad_url)
        guid = parse_apply_guid(page[0]) if page is not None else None
        if guid is not None and _same_employer(session, guid, name):
            return True
    return False


def _find_page(session, name: str) -> str | None:
    """The address of the page on the employer's own website that lists the ads it takes applications for on Visma
    Recruit, found from the website guessed from *name* through its careers links (two levels, at most
    ``_MAX_PROBE_PAGES`` pages); None when no page lists ads of *name*."""
    for site in _site_guesses(name):
        start = _read(session, site)
        if start is None:
            continue
        queue, seen, fetched = [(start[0], start[1], 0)], {_norm(start[1])}, 1
        while queue:
            html, where, depth = queue.pop(0)
            if depth and _page_is_the_employers(session, html, where, name):   # (the start page only teases a few)
                return _norm(where)
            if depth >= 2:
                continue
            links = sorted(career_links(html, where), key=lambda l: "ledig" not in l.lower())
            for link in links[:4]:
                if _norm(link) in seen or fetched >= _MAX_PROBE_PAGES:
                    continue
                seen.add(_norm(link))
                page = _read(session, link)
                fetched += 1
                if page is not None:
                    queue.append((page[0], page[1], depth + 1))
    return None


def resolve(session, det: Detection, url: str) -> Detection:
    """*det* (an ad link on ``recruit.visma.com``) with what the ad shows: the employer's name, and its job list when
    the employer's own website links one (the entry to follow), else its website when the ad names one, for `follow`
    to try. *det* itself for a link that is no ad (a list's, a career site's) and when the ad's JSON cannot be read
    or names no employer."""
    if det.entry:
        return det
    guid = assignment_guid(url)
    if guid is None:
        return det
    try:
        data = session.get(_SETTINGS_URL, params={"guidAssignment": guid}, headers={"Accept": "application/json"}).json()
    except (requests.RequestException, RobotsBlocked, ValueError):
        return det
    name, site = employer_of(data)
    if name is None and site is None:
        return det
    who = name or site
    evidence = f"{det.evidence}; the ad names the employer {who}"
    if name is not None and site is None:
        found = _find_list(session, name)
        if found is not None:
            guid, page = found
            return Detection(det.platform, guid, f"{evidence}; its website {page} links the job list {guid}", None, name, page)
        where = _find_page(session, name)
        if where is not None:
            return Detection(det.platform, where, f"{evidence}; {where} lists its ads, read through Visma Recruit", None, name, where)
    return Detection(det.platform, None, evidence, det.refusal, name, site)
