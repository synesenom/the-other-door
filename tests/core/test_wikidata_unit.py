"""An employer's own website from its name, read from Wikidata (issue #566): the name a register gives
("Telia Sverige AB") trimmed to the one Wikidata knows, the organisation picked among the namesakes, and the
lookup's cache, budget and failures. The payloads are saved real answers (`tests/fixtures/employer_site/`)."""

import re

import pytest
import responses

from door.core import wikidata
from door.scrapers.http_client import PoliteSession
import wikidata_utils

_load = wikidata_utils.load
_entities = wikidata_utils.entities
wikidata_answers = wikidata_utils.serve_wikidata


def _session():
    return PoliteSession(min_delay=0, max_delay=0, max_retries=0)


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


# --- the name Wikidata knows ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, core", [
    ("H & M Hennes & Mauritz GBC AB", "H & M Hennes & Mauritz"),
    ("H & M Hennes & Mauritz Sverige AB", "H & M Hennes & Mauritz"),
    ("Telia Sverige AB", "Telia"),
    ("Hilti Svenska Aktiebolag", "Hilti"),
    ("Axiomatics", "Axiomatics"),
    ("Internationella Engelska Skolan i Sverige AB", "Internationella Engelska Skolan"),
    ("Novo Nordisk A/S", "Novo Nordisk"),
    ("Svenska Spel", "Svenska Spel"),    # a country word in front is the name itself
    ("Svenska AB", "Svenska"),           # never trimmed to nothing
])
def test_a_registers_name_is_trimmed_of_legal_forms_and_subsidiary_words_at_its_end(name, core):
    assert wikidata.trimmed(name) == core


def test_the_name_is_searched_with_its_subsidiary_words_first_then_without():
    assert wikidata.queries("Telia Sverige AB") == ["Telia Sverige", "Telia"]
    assert wikidata.queries("H & M Hennes & Mauritz GBC AB") == ["H & M Hennes & Mauritz GBC", "H & M Hennes & Mauritz"]
    assert wikidata.queries("Axiomatics") == ["Axiomatics"]


def test_only_the_hits_whose_label_or_matched_name_is_the_employers_are_read():
    hits = _load("search_telia_sverige.json")["search"] + _load("search_telia.json")["search"]

    ids = wikidata.matching_ids(hits, "Telia Sverige AB")

    assert ids[0] == "Q4567911"
    assert "Q97998570" in ids                       # a motion titled "Telia": its name matches, its kind does not
    assert not {"Q862303", "Q6515085", "Q1295663"} & set(ids)   # Telia Company, Telia Norge, Telia Eesti


def test_a_hit_matched_by_an_alias_counts():
    assert wikidata.matching_ids(_load("search_hm.json")["search"], "H & M Hennes & Mauritz Sverige AB")[:2] == \
        ["Q188326", "Q64023001"]   # H&M by its alias "H & M Hennes & Mauritz AB", then H&M's GBC


def test_an_organisation_is_told_from_a_namesake_person_document_or_place():
    entities = _entities()
    assert wikidata.is_organisation(entities["Q188326"])
    assert wikidata.is_organisation(entities["Q4567911"])
    assert not wikidata.is_organisation(entities["Q97998570"])     # a parliamentary motion
    assert not wikidata.is_organisation(entities["Q123581685"])    # a family name
    assert not wikidata.is_organisation(entities["Q7697232"])      # a village


def test_the_website_on_the_profiles_country_domain_is_preferred_then_a_com_one():
    entities = _entities()
    assert wikidata.website_of(entities["Q1361530"], ("se",)) == "https://www.hilti.com/"
    assert wikidata.website_of(entities["Q1361530"], ("de",)) == "https://www.hilti.de/"
    assert wikidata.website_of(entities["Q4567911"], ("se",)) == "http://www.telia.se"
    assert wikidata.website_of(entities["Q97998570"], ("se",)) is None


def test_an_organisation_in_the_profiles_country_is_chosen_over_one_abroad():
    entities = _entities()
    ids = ["Q6515085", "Q4567911"]     # Telia Norge first, Telia Sverige second

    assert wikidata.choose(entities, ids, "Q34") == "Q4567911"
    assert wikidata.choose(entities, ids, "Q20") == "Q6515085"


def test_an_organisation_without_a_website_is_passed_over_for_one_with():
    assert wikidata.choose(_entities(), ["Q64023001", "Q188326"], "Q34") == "Q188326"


def test_nothing_is_chosen_from_namesakes_that_are_no_organisation():
    assert wikidata.choose(_entities(), ["Q97998570", "Q97998379", "Q123581685"], "Q34") is None


# --- the lookup ------------------------------------------------------------------------------------------

@responses.activate
def test_a_swedish_subsidiary_is_found_with_its_website_and_its_parents():
    wikidata_answers()

    found, note = wikidata.Lookup("Stockholm").employer(_session(), "Telia Sverige AB")

    assert note is None
    assert (found.qid, found.label, found.website, found.local) == ("Q4567911", "Telia Sverige", "http://www.telia.se", True)
    assert found.sites() == ["http://www.telia.se", "https://www.teliacompany.com/sv"]
    assert found.names() == ["Telia Sverige", "Telia Company"]


@responses.activate
def test_a_foreign_group_is_found_when_the_country_has_none_of_that_name():
    wikidata_answers()

    found, _ = wikidata.Lookup("Stockholm").employer(_session(), "Hilti Svenska Aktiebolag")

    assert (found.qid, found.website, found.local) == ("Q1361530", "https://www.hilti.com/", False)


@responses.activate
def test_two_names_of_one_employer_are_looked_up_once():
    wikidata_answers()
    lookup = wikidata.Lookup("Stockholm")

    first, _ = lookup.employer(_session(), "H & M Hennes & Mauritz GBC AB")
    calls = len(responses.calls)
    second, _ = lookup.employer(_session(), "H & M Hennes & Mauritz Sverige AB")

    assert first.qid == "Q188326" and first.website == "https://www2.hm.com"   # its preferred website
    assert second == first and len(responses.calls) == calls


@responses.activate
def test_an_unknown_name_says_why():
    wikidata_answers()

    found, note = wikidata.Lookup("Stockholm").employer(_session(), "Nobody Known AB")

    assert found is None and "Wikidata" in note and "Nobody Known" in note


@responses.activate
def test_the_lookups_of_one_run_are_capped():
    wikidata_answers()
    lookup = wikidata.Lookup("Stockholm", max_lookups=1)

    lookup.employer(_session(), "Telia Sverige AB")
    calls = len(responses.calls)
    found, note = lookup.employer(_session(), "Hilti Svenska Aktiebolag")

    assert found is None and "budget" in note and len(responses.calls) == calls


@pytest.fixture
def rests(monkeypatch):
    """The waits `Lookup` asks for, not slept: a clock that moves by each wait."""
    from types import SimpleNamespace
    waited, now = [], [1000.0]

    def rest(seconds):
        waited.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(wikidata, "_rest", rest)
    monkeypatch.setattr(wikidata, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=rest))
    return waited


@responses.activate
def test_a_second_refusal_stops_the_lookups_for_the_run_and_is_no_error(rests):
    responses.add(responses.GET, re.compile(r"https://www\.wikidata\.org/.*"), status=429)
    lookup = wikidata.Lookup("Stockholm")

    found, note = lookup.employer(_session(), "Telia Sverige AB")
    calls = len(responses.calls)
    again, again_note = lookup.employer(_session(), "Hilti Svenska Aktiebolag")

    assert found is None and "429" in note and calls == 2    # asked, waited, asked once more
    assert again is None and "429" in again_note and len(responses.calls) == calls
    assert len(rests) == 1


@responses.activate
def test_one_429_is_waited_out_and_the_request_retried(rests):
    responses.add(responses.GET, re.compile(r"https://www\.wikidata\.org/.*"), status=429, headers={"Retry-After": "7"})
    responses.add_callback(responses.GET, wikidata_utils.WIKIDATA_API, callback=wikidata_utils.answer)
    lookup = wikidata.Lookup("Stockholm")

    found, note = lookup.employer(_session(), "Telia Sverige AB")

    assert found is not None and found.qid == "Q4567911" and note is None
    assert rests == [7.0]


@responses.activate
def test_a_server_error_is_waited_out_too_and_the_wait_is_capped(rests):
    responses.add(responses.GET, re.compile(r"https://www\.wikidata\.org/.*"), status=503, headers={"Retry-After": "600"})
    responses.add_callback(responses.GET, wikidata_utils.WIKIDATA_API, callback=wikidata_utils.answer)

    found, _ = wikidata.Lookup("Stockholm").employer(_session(), "Telia Sverige AB")

    assert found is not None
    assert rests == [wikidata._REST_S]


@responses.activate
def test_without_retry_after_a_fixed_rest_is_taken(rests):
    responses.add(responses.GET, re.compile(r"https://www\.wikidata\.org/.*"), status=429)
    responses.add_callback(responses.GET, wikidata_utils.WIKIDATA_API, callback=wikidata_utils.answer)

    wikidata.Lookup("Stockholm").employer(_session(), "Telia Sverige AB")

    assert rests == [wikidata._REST_S]


@responses.activate
def test_lookups_in_other_threads_wait_while_one_rests(monkeypatch):
    """While one thread waits out a 429 another does not ask Wikidata: it waits for the rest to end first."""
    import threading
    import time

    started, released = threading.Event(), threading.Event()
    waits = []

    def rest(seconds):
        waits.append(seconds)
        started.set()
        released.wait(5)

    monkeypatch.setattr(wikidata, "_rest", rest)
    responses.add(responses.GET, re.compile(r"https://www\.wikidata\.org/.*"), status=429)
    responses.add_callback(responses.GET, wikidata_utils.WIKIDATA_API, callback=wikidata_utils.answer)
    lookup = wikidata.Lookup("Stockholm")
    first = threading.Thread(target=lookup.employer, args=(_session(), "Telia Sverige AB"))
    first.start()
    assert started.wait(5)
    calls = len(responses.calls)
    second = threading.Thread(target=lookup.employer, args=(_session(), "Hilti Svenska Aktiebolag"))
    second.start()
    time.sleep(0.3)

    assert len(responses.calls) == calls     # the second one asked nothing while the first rests
    released.set()
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()


def test_the_notes_of_a_lookup_that_never_asked_are_told_from_the_rest():
    assert wikidata.is_unasked("Wikidata not asked: this run's budget of 60 lookups is spent")
    assert wikidata.is_unasked("Wikidata stopped answering this run (it answered 429)")
    assert not wikidata.is_unasked("Wikidata knows no organisation named 'X' with a website")


@responses.activate
def test_without_a_country_the_search_is_in_english_and_no_country_is_preferred():
    wikidata_answers()

    found, _ = wikidata.Lookup("").employer(_session(), "Hilti Svenska Aktiebolag")

    assert found.qid == "Q1361530" and found.local is False
    searches = [c.request.url for c in responses.calls if "wbsearchentities" in c.request.url]
    assert searches and all("language=en" in url for url in searches)
    assert not any("haswbstatement" in c.request.url for c in responses.calls)
