"""The saved Wikidata answers of `tests/fixtures/employer_site/` (issue #566), served through `responses`."""

import json
import re
from urllib.parse import parse_qsl, urlsplit

import responses

from paths import TESTS_DIR

FX = TESTS_DIR / "fixtures" / "employer_site"
SEARCHES = {
    "H & M Hennes & Mauritz GBC": "search_hm_gbc.json", "H & M Hennes & Mauritz": "search_hm.json",
    "Telia Sverige": "search_telia_sverige.json", "Telia": "search_telia.json",
    "Hilti Svenska": "search_hilti_svenska.json", "Hilti": "search_hilti.json",
}


def load(name: str):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def entities() -> dict:
    return load("entities.json")["entities"]


def text(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def answer(request):
    """Wikidata's answer to *request* from the saved answers (a `responses` callback): a search by its text (one
    not saved finds nothing), an entity read by its ids (an id with no saved entity is answered as Wikidata
    answers an item it does not hold), the country item by its ISO code."""
    params = dict(parse_qsl(urlsplit(request.url).query))
    if params.get("action") == "wbsearchentities":
        name = SEARCHES.get(params.get("search", ""))
        return 200, {}, json.dumps(load(name) if name else {"search": []})
    if params.get("action") == "wbgetentities":
        saved = entities()
        ids = params.get("ids", "").split("|")
        return 200, {}, json.dumps({"entities": {q: saved.get(q, {"id": q, "missing": ""}) for q in ids}})
    if params.get("action") == "query" and params.get("srsearch") == "haswbstatement:P297=SE":
        return 200, {}, json.dumps(load("country_se.json"))
    return 404, {}, ""


WIKIDATA_API = re.compile(r"https://www\.wikidata\.org/w/api\.php.*")


def serve_wikidata() -> None:
    """Answer Wikidata's API from the saved answers (`answer`)."""
    responses.add_callback(responses.GET, WIKIDATA_API, callback=answer)
