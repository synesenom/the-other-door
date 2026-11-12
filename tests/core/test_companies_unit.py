"""`door.core.companies`: the employer list in `profile/companies.json`."""

from datetime import datetime, timedelta, timezone

import json

import pytest

from door.core import companies
from door.core.profile_loader import ConfigError, load_config
from profile_utils import write_config

NOW = "2026-01-02T03:04:05+00:00"


def _write(profile_dir, items):
    (profile_dir / "companies.json").write_text(json.dumps({"version": 1, "companies": items}))


def test_a_missing_file_is_an_empty_list(tmp_path):
    assert companies.load(tmp_path) == []


def test_save_then_load_round_trips_and_writes_the_documented_shape(tmp_path):
    item = companies.Company(name="BEC", feed=companies.Feed(platform="hr_manager", id="bec"), status="followed",
                             found_via="manual", first_seen=NOW, last_checked=NOW)
    companies.save(tmp_path, [item])

    data = json.loads((tmp_path / "companies.json").read_text())
    assert data["version"] == 1
    assert data["companies"][0]["feed"] == {"platform": "hr_manager", "id": "bec"}
    assert companies.load(tmp_path) == [item]
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("text, fragment", [
    ("{not json", "invalid JSON"),
    ('{"version": 2, "companies": []}', "version"),
    ('{"version": 1, "companies": [{"name": "X", "status": "followed", "found_via": "manual"}]}', "feed"),
    ('{"version": 1, "companies": [{"name": "X", "status": "maybe", "found_via": "manual"}]}', "status"),
    ('{"version": 1, "companies": [{"name": "X", "feed": {"platform": "nope", "id": "x"}, "status": "followed", '
     '"found_via": "manual"}]}', "platform"),
])
def test_an_invalid_file_gives_a_clear_error_naming_the_file(tmp_path, text, fragment):
    (tmp_path / "companies.json").write_text(text)
    with pytest.raises(companies.CompaniesError) as exc:
        companies.load(tmp_path)
    assert "companies.json" in str(exc.value) and fragment in str(exc.value)


def test_lookup_by_name_ignores_case_and_company_suffixes():
    items = [companies.Company(name="Novo Nordisk A/S", status="unresolved", found_via="manual")]
    assert companies.find(items, "novo nordisk") is items[0]
    assert companies.find(items, "NOVO NORDISK ApS") is items[0]
    assert companies.find(items, "Novo") is None


def test_lookup_by_feed_ignores_case():
    item = companies.Company(name="Trustpilot", feed=companies.Feed(platform="greenhouse", id="Trustpilot"),
                             status="followed", found_via="manual")
    assert companies.find_by_feed([item], "greenhouse", "trustpilot") is item
    assert companies.find_by_feed([item], "lever", "trustpilot") is None


def test_record_adds_then_updates_without_losing_first_seen():
    items: list = []
    first, is_new = companies.record(items, "BEC", feed=("hr_manager", "bec"), status="followed",
                                     found_via="manual", evidence="link", now=NOW)
    assert is_new and items == [first] and first.first_seen == NOW

    again, is_new = companies.record(items, "bec", feed=("hr_manager", "bec"), status="followed",
                                     found_via="linkedin", evidence="again", now="2027-01-01T00:00:00+00:00")
    assert not is_new and len(items) == 1
    assert again.first_seen == NOW and again.last_checked.startswith("2027")
    assert again.found_via == "manual"   # how it was first found stays


def test_a_failed_recheck_never_unfollows():
    items: list = []
    companies.record(items, "BEC", feed=("hr_manager", "bec"), status="followed", found_via="manual", now=NOW)
    kept, _ = companies.record(items, "BEC", feed=None, status="unresolved", reason="not found",
                               found_via="linkedin", now=NOW)
    assert kept.status == "followed" and kept.feed.id == "bec"


def test_an_unresolved_company_can_be_resolved_later():
    items: list = []
    companies.record(items, "Acme", feed=None, status="unresolved", reason="not found", found_via="jobindex", now=NOW)
    item, _ = companies.record(items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual", now=NOW)
    assert item.status == "followed" and item.reason is None and item.feed.platform == "lever"


def test_the_same_feed_under_another_name_is_one_employer():
    items: list = []
    companies.record(items, "BEC Financial Technologies", feed=("hr_manager", "bec"), status="followed",
                     found_via="manual", now=NOW)
    companies.record(items, "BEC", feed=("hr_manager", "bec"), status="followed", found_via="manual", now=NOW)
    assert len(items) == 1


def test_another_name_on_a_followed_feed_is_kept_as_an_also_known_as_not_a_second_entry():
    items: list = []
    companies.record(items, "Region Hovedstaden", feed=("hr_manager", "regionh"), status="followed",
                     found_via="manual", now=NOW)
    company, is_new = companies.record(items, "Herlev og Gentofte Hospital", feed=("hr_manager", "regionh"),
                                       status="followed", found_via="linkedin", now=NOW,
                                       evidence="cid 342 is the customer of regionh")
    assert not is_new and len(items) == 1 and company.name == "Region Hovedstaden"
    assert items[0].aliases == ["Herlev og Gentofte Hospital"] and items[0].found_via == "manual"
    # the name now finds the employer, so `follow` need not look at it again
    assert companies.find(items, "herlev og gentofte hospital") is items[0]
    assert companies.is_settled(items, "Herlev og Gentofte Hospital")
    # again, and under the primary name itself: nothing is added twice
    companies.record(items, "Herlev og Gentofte Hospital", feed=("hr_manager", "regionh"), status="followed",
                     found_via="linkedin", now=NOW)
    companies.record(items, "Region Hovedstaden", feed=("hr_manager", "regionh"), status="followed",
                     found_via="manual", now=NOW)
    assert items[0].aliases == ["Herlev og Gentofte Hospital"]


def test_a_feed_followed_under_several_names_is_scraped_once(tmp_path):
    items: list = []
    companies.record(items, "Region Hovedstaden", feed=("hr_manager", "regionh"), status="followed", found_via="manual")
    companies.record(items, "Frederiksberg Hospital", feed=("hr_manager", "regionh"), status="followed", found_via="linkedin")
    companies.save(tmp_path, items)
    assert companies.feed_config(tmp_path) == {"hr_manager_aliases": ["regionh"]}
    assert companies.load(tmp_path)[0].aliases == ["Frederiksberg Hospital"]


def test_remove_by_an_also_known_as_name_removes_the_employer():
    items: list = []
    companies.record(items, "Region Hovedstaden", feed=("hr_manager", "regionh"), status="followed", found_via="manual")
    companies.record(items, "Frederiksberg Hospital", feed=("hr_manager", "regionh"), status="followed", found_via="linkedin")
    assert [c.name for c in companies.remove(items, "Frederiksberg Hospital")] == ["Region Hovedstaden"] and items == []


def test_remove_by_name_returns_what_it_removed():
    items = [companies.Company(name="A", status="unresolved", found_via="manual"),
             companies.Company(name="B ApS", status="unresolved", found_via="manual")]
    removed = companies.remove(items, "b")
    assert [c.name for c in removed] == ["B ApS"] and [c.name for c in items] == ["A"]
    assert companies.remove(items, "zzz") == []


def test_feed_entries_lists_only_followed_ids_of_a_platform(tmp_path):
    _write(tmp_path, [
        {"name": "A", "feed": {"platform": "lever", "id": "a"}, "status": "followed", "found_via": "manual"},
        {"name": "B", "feed": {"platform": "lever", "id": "b"}, "status": "followed", "found_via": "manual"},
        {"name": "C", "feed": {"platform": "greenhouse", "id": "c"}, "status": "followed", "found_via": "manual"},
        {"name": "D", "status": "unresolved", "reason": "x", "found_via": "manual"},
    ])
    assert companies.feed_entries(tmp_path, "lever") == ["a", "b"]
    assert companies.feed_entries(tmp_path, "ashby") == []
    assert companies.feed_config(tmp_path) == {"lever_companies": ["a", "b"], "greenhouse_boards": ["c"]}


@pytest.mark.parametrize("entry, name", [
    ("trustpilot", "Trustpilot"),
    ("my-company", "My Company"),
    ("https://boards.greenhouse.io/acme", "Acme"),
    ("careers.publicissapient.com", "Publicissapient"),
    ("https://careers.novonordisk.com", "Novonordisk"),
])
def test_guess_name_from_a_feed_entry(entry, name):
    assert companies.guess_name(entry) == name


def _entry(name, status, last_checked, feed=None):
    return companies.Company(name=name, feed=companies.Feed(platform=feed[0], id=feed[1]) if feed else None,
                             status=status, found_via="manual", last_checked=last_checked)


def test_a_followed_employer_is_settled_whatever_its_age():
    from datetime import datetime, timezone

    items = [_entry("Pleo ApS", "followed", "2020-01-01T00:00:00+00:00", ("ashby", "pleo"))]
    assert companies.is_settled(items, "pleo", datetime(2026, 10, 1, tzinfo=timezone.utc))


def test_an_unfollowable_or_unresolved_employer_is_settled_for_ninety_days():
    from datetime import datetime, timezone

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    items = [_entry("Fresh", "unresolved", "2026-08-01T00:00:00+00:00"),
             _entry("Old", "unfollowable", "2026-06-01T00:00:00+00:00"),
             _entry("Undated", "unresolved", None)]
    assert companies.is_settled(items, "Fresh", now)
    assert not companies.is_settled(items, "Old", now)
    assert not companies.is_settled(items, "Undated", now)
    assert not companies.is_settled(items, "Nobody", now)


# --- dormant: followed employers that yield nothing relevant ------------------------------------------

def _followed(items, name, first_seen, found_via="jobindex", last_relevant=None):
    company, _ = companies.record(items, name, feed=("lever", name.lower()), status="followed",
                                  found_via=found_via, now=first_seen)
    company.last_relevant = last_relevant
    return company


def _days_ago(n, now):
    return (now - timedelta(days=n)).isoformat()


def test_an_employer_with_no_relevant_job_for_the_period_becomes_dormant():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    items = []
    old = _followed(items, "Old", _days_ago(100, now))
    fresh = _followed(items, "Fresh", _days_ago(10, now))
    kept = _followed(items, "Kept", _days_ago(100, now), last_relevant=_days_ago(5, now))
    stale = _followed(items, "Stale", _days_ago(300, now), last_relevant=_days_ago(95, now))

    retired = companies.retire_idle(items, 90, now)

    assert [c.name for c in retired] == ["Old", "Stale"]
    assert (old.status, old.reason) == ("dormant", "no relevant job in 90 days") and old.feed is not None
    assert fresh.status == kept.status == "followed"
    assert stale.status == "dormant"


def test_a_manual_employer_is_never_retired_and_zero_means_never():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    items = []
    by_hand = _followed(items, "ByHand", _days_ago(400, now), found_via="manual")
    other = _followed(items, "Other", _days_ago(400, now))
    assert companies.retire_idle(items, 0, now) == []
    assert companies.retire_idle(items, 90, now) == [other]
    assert by_hand.status == "followed"


def test_a_dormant_employer_is_not_settled_so_a_fitting_ad_queues_it_again():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    items = []
    _followed(items, "Old", _days_ago(100, now))
    companies.retire_idle(items, 90, now)
    assert companies.is_settled(items, "Old", now) is False


def test_reactivating_a_dormant_employer_restarts_its_clock():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    items = []
    old = _followed(items, "Old", _days_ago(100, now))
    companies.retire_idle(items, 90, now)
    companies.reactivate(old, now.isoformat())
    assert (old.status, old.reason, old.last_relevant) == ("followed", None, now.isoformat())
    assert companies.retire_idle(items, 90, now) == []


def test_a_miss_never_drops_the_feed_of_a_dormant_employer():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    items = []
    old = _followed(items, "Old", _days_ago(100, now))
    companies.retire_idle(items, 90, now)
    companies.record(items, "Old", feed=None, status="unresolved", found_via="jobindex", reason="x")
    assert old.status == "dormant" and old.feed is not None


def test_mark_relevant_stamps_the_employer_by_name_or_also_name():
    items = []
    old = _followed(items, "Old", "2026-01-01T00:00:00+00:00")
    old.aliases.append("Old Group")
    assert companies.mark_relevant(items, "Old Group", "2026-09-01T00:00:00+00:00") is old
    assert old.last_relevant == "2026-09-01T00:00:00+00:00"
    assert companies.mark_relevant(items, "Nobody", "2026-09-01T00:00:00+00:00") is None


# --- followed names for the scrapers ------------------------------------------------------------------

def test_entry_key_lowercases_and_drops_scheme_and_trailing_slash():
    assert companies.entry_key("  HTTPS://Boards.Greenhouse.io/Acme/ ") == "boards.greenhouse.io/acme"
    assert companies.entry_key("acme") == "acme"


def _names_items():
    return [_entry("Acme A/S", "followed", None, ("lever", "Acme")),
            _entry("Initech", "followed", None, ("greenhouse", "https://boards.greenhouse.io/initech/")),
            _entry("Gone", "dormant", None, ("lever", "gone")),
            _entry("Nofeed", "unfollowable", None)]


def test_feed_names_maps_followed_entries_to_names_by_config_key():
    assert companies.feed_names(_names_items()) == {
        "lever_companies": {"acme": "Acme A/S"},
        "greenhouse_boards": {"boards.greenhouse.io/initech": "Initech"},
    }


def test_feed_names_only_restricts_to_the_given_companies():
    items = _names_items()
    assert companies.feed_names(items[:1]) == {"lever_companies": {"acme": "Acme A/S"}}


# --- a feed shared by several employers (#308) ---------------------------------------------------

SHARED_FEED = ("hr_manager", "statensrekrutteringsloesning_tr")
SHARED_NAME = "Statens Rekrutteringsløsning"


def _rec(items, name, feed=SHARED_FEED, status="followed", **kw):
    return companies.record(items, name, feed=feed, status=status, found_via=kw.pop("found_via", "linkedin"),
                            evidence=kw.pop("evidence", "feed found"), now=kw.pop("now", NOW), **kw)


def test_a_shared_feed_is_recorded_once_under_its_own_name():
    items = []
    entry, is_new = _rec(items, "Trafikstyrelsen")
    assert is_new and entry.name == SHARED_NAME and entry.aliases == []
    assert "Trafikstyrelsen" in entry.evidence

    again, is_new = _rec(items, "Forsvaret")
    assert not is_new and again is entry and len(items) == 1
    assert "Trafikstyrelsen" in entry.evidence and "Forsvaret" in entry.evidence
    _rec(items, "Forsvaret")
    assert entry.evidence.count("Forsvaret") == 1


def test_a_local_agency_entry_on_the_shared_feed_is_renamed():
    ku = companies.Company(name="Københavns Universitet", feed=companies.Feed(platform="hr_manager", id=SHARED_FEED[1]),
                           status="followed", found_via="manual", aliases=["KU - SUND"], first_seen="2025-01-01T00:00:00+00:00")
    items = [ku]
    entry, is_new = _rec(items, "GEUS")
    assert not is_new and len(items) == 1 and entry.name == SHARED_NAME and entry.aliases == []
    assert entry.found_via == "manual" and entry.first_seen == "2025-01-01T00:00:00+00:00"
    for agency in ("Københavns Universitet", "KU - SUND", "GEUS"):
        assert agency in entry.evidence


def test_a_stale_unresolved_entry_named_like_the_agency_is_dropped():
    items = [companies.Company(name="Trafikstyrelsen", status="unresolved", reason="no alias", found_via="linkedin"),
             companies.Company(name="Other", status="unresolved", reason="x", found_via="linkedin")]
    _rec(items, "Trafikstyrelsen")
    assert sorted(c.name for c in items) == ["Other", SHARED_NAME]


def test_an_agency_followed_on_its_own_feed_is_untouched():
    ku = companies.Company(name="Københavns Universitet", feed=companies.Feed(platform="hr_manager", id="ku"),
                           status="followed", found_via="manual")
    items = [ku]
    _rec(items, "Trafikstyrelsen")
    assert ku.name == "Københavns Universitet" and len(items) == 2


def test_a_dormant_shared_feed_is_followed_again():
    items = []
    entry, _ = _rec(items, "Trafikstyrelsen")
    entry.status, entry.reason, entry.last_relevant = "dormant", "idle", "2025-01-01T00:00:00+00:00"
    _rec(items, "Forsvaret", now="2026-02-02T00:00:00+00:00")
    assert entry.status == "followed" and entry.reason is None and entry.last_relevant == "2026-02-02T00:00:00+00:00"


def test_a_feed_that_is_not_shared_still_merges_names_into_also():
    items = []
    _rec(items, "BEC", feed=("hr_manager", "bec"))
    entry, _ = _rec(items, "BEC Financial", feed=("hr_manager", "bec"))
    assert entry.name == "BEC" and entry.aliases == ["BEC Financial"]


def test_a_posting_of_a_shared_feed_stamps_the_feed_entry():
    items = []
    entry, _ = _rec(items, "Trafikstyrelsen")
    stray = companies.Company(name="Stray", status="unresolved", reason="x", found_via="linkedin")
    items.append(stray)
    assert companies.mark_relevant_posting(
        items, "Det Kongelige Bibliotek", "hr_manager.statensrekrutteringsloesning_tr-9", "T1") is True
    assert entry.last_relevant == "T1"
    assert companies.mark_relevant_posting(items, "Unknown", "hr_manager.bec-1", "T2") is False
    assert entry.last_relevant == "T1" and stray.last_relevant is None
    assert companies.mark_relevant_posting(items, "Stray", "hr_manager.bec-1", "T3") is True
    assert stray.last_relevant == "T3"


# --- aliases (#314) ------------------------------------------------------------------------------------

def _raw(name, **kw):
    return {"name": name, "status": "unresolved", "found_via": "manual", **kw}


def test_an_old_also_key_loads_as_aliases_and_saves_as_aliases(tmp_path):
    _write(tmp_path, [_raw("Acme", also=["Acme Group"])])
    items = companies.load(tmp_path)
    assert items[0].aliases == ["Acme Group"]
    companies.save(tmp_path, items)
    saved = json.loads((tmp_path / "companies.json").read_text())["companies"][0]
    assert saved["aliases"] == ["Acme Group"] and "also" not in saved


def test_an_entry_with_both_keys_merges_them_without_duplicates(tmp_path):
    _write(tmp_path, [_raw("Acme", also=["Acme Group", "Acme X"], aliases=["acme group", "Acme Y"])])
    assert companies.load(tmp_path)[0].aliases == ["acme group", "Acme Y", "Acme X"]


def test_find_matches_an_alias_case_and_suffix_insensitively():
    items = [companies.Company(name="Novo Nordisk", status="unresolved", found_via="manual", aliases=["Novo"])]
    assert companies.find(items, "NOVO A/S") is items[0]
    assert companies.find(items, "Novo Nordisk A/S") is items[0]
    assert companies.find(items, "Lego") is None


def test_alias_settles_and_is_marked_relevant():
    items = []
    old = _followed(items, "Old", "2026-01-01T00:00:00+00:00")
    old.aliases.append("Old Group")
    assert companies.is_settled(items, "Old Group")
    assert companies.mark_relevant(items, "old group", "2026-09-01T00:00:00+00:00") is old


def _two(**kw):
    a = companies.Company(name="LEGO", status="unresolved", found_via="jobindex", evidence="a ev",
                          first_seen="2026-02-01T00:00:00+00:00", last_checked="2026-03-01T00:00:00+00:00",
                          last_relevant="2026-03-02T00:00:00+00:00", aliases=["LEGO Group"])
    b = companies.Company(name="LEGO System A/S", status="unresolved", found_via="linkedin", evidence="b ev",
                          first_seen="2026-01-01T00:00:00+00:00", last_checked="2026-04-01T00:00:00+00:00",
                          last_relevant="2026-01-02T00:00:00+00:00", aliases=["LEGO Group", "Lego Billund"])
    return a, b


def test_merge_keeps_a_name_and_unions_aliases_evidence_and_dates():
    a, b = _two()
    items = [a, b]
    merged = companies.merge(items, "LEGO", "LEGO System A/S")
    assert merged is a and items == [a]
    assert a.name == "LEGO"
    # "LEGO Group" has the same name_key as "LEGO": never an alias of its own employer
    assert a.aliases == ["LEGO System A/S", "Lego Billund"]
    assert "a ev" in a.evidence and "b ev" in a.evidence
    assert a.first_seen == "2026-01-01T00:00:00+00:00"
    assert a.last_checked == "2026-04-01T00:00:00+00:00"
    assert a.last_relevant == "2026-03-02T00:00:00+00:00"


def test_merge_adds_bs_name_as_an_alias_when_it_differs():
    a = companies.Company(name="Novo", status="unresolved", found_via="manual")
    b = companies.Company(name="Novo Nordisk", status="unresolved", found_via="manual", aliases=["NN"])
    companies.merge([a, b], "Novo", "Novo Nordisk")
    assert a.aliases == ["Novo Nordisk", "NN"]


def test_merge_the_followed_one_wins_its_feed_status_and_reason():
    items = []
    a = companies.Company(name="Tryg", status="unresolved", found_via="jobindex", reason="none")
    b = _followed(items, "Tryg Forsikring", "2026-01-01T00:00:00+00:00")
    merged = companies.merge([a, b], "Tryg", "Tryg Forsikring")
    assert merged.status == "followed" and merged.feed == b.feed and merged.reason is None


def test_merge_an_unresolved_b_into_a_followed_a_keeps_the_feed():
    items = []
    a = _followed(items, "Tryg", "2026-01-01T00:00:00+00:00")
    b = companies.Company(name="Tryg Forsikring", status="unresolved", found_via="jobindex")
    merged = companies.merge([a, b], "Tryg", "Tryg Forsikring")
    assert merged.status == "followed" and merged.feed == a.feed


def test_merge_two_followed_on_different_feeds_is_refused():
    items = []
    a = _followed(items, "Tryg", "2026-01-01T00:00:00+00:00")
    b = _followed(items, "Tryg Forsikring", "2026-01-01T00:00:00+00:00")
    with pytest.raises(companies.CompaniesError, match="different feeds"):
        companies.merge([a, b], "Tryg", "Tryg Forsikring")


def test_merge_unknown_or_same_entry_is_refused():
    a, b = _two()
    with pytest.raises(companies.CompaniesError, match="not on the list"):
        companies.merge([a, b], "LEGO", "Nobody")
    with pytest.raises(companies.CompaniesError, match="not on the list"):
        companies.merge([a, b], "Nobody", "LEGO")
    with pytest.raises(companies.CompaniesError, match="same"):
        companies.merge([a, b], "LEGO", "LEGO Group")


def _dup_items():
    items = []
    companies.record(items, "LEGO", feed=("lever", "lego"), status="followed", found_via="manual", now=NOW)
    items.append(companies.Company(name="LEGO System A/S", feed=companies.Feed(platform="lever", id="LEGO"),
                                   status="followed", found_via="linkedin"))
    items.append(companies.Company(name="Tryg", status="unresolved", found_via="jobindex", aliases=["Tryg Forsikring"]))
    items.append(companies.Company(name="Tryg Forsikring A/S", status="unfollowable", found_via="linkedin"))
    items.append(companies.Company(name="Solo", status="unresolved", found_via="linkedin"))
    items.append(companies.Company(name="Agency 1", feed=companies.Feed(platform=SHARED_FEED[0], id=SHARED_FEED[1]),
                                   status="followed", found_via="manual"))
    items.append(companies.Company(name="Agency 2", feed=companies.Feed(platform=SHARED_FEED[0], id=SHARED_FEED[1]),
                                   status="followed", found_via="manual"))
    return items


def test_merge_candidates_groups_entries_sharing_a_feed_or_a_name_key():
    groups = companies.merge_candidates(_dup_items())
    assert {"names": ["LEGO", "LEGO System A/S"], "reason": "same feed"} in groups
    assert {"names": ["Tryg", "Tryg Forsikring A/S"], "reason": "same name"} in groups
    assert len(groups) == 2  # no group of one, no shared portal


def test_employer_of_gives_the_entry_name_for_a_name_or_alias_or_a_shared_feed_job():
    items = [companies.Company(name="Novo Nordisk", status="unresolved", found_via="manual", aliases=["Novo"]),
             companies.Company(name=SHARED_NAME, feed=companies.Feed(platform=SHARED_FEED[0], id=SHARED_FEED[1]),
                               status="followed", found_via="manual")]
    assert companies.employer_of(items, "Novo A/S", "jobindex.1") == "Novo Nordisk"
    assert companies.employer_of(items, "Forsvaret", f"hr_manager.{SHARED_FEED[1]}-12") == SHARED_NAME
    assert companies.employer_of(items, "Nobody", "jobindex.2") is None


def test_merge_tells_apart_entries_that_share_a_name_key():
    a = companies.Company(name="Tryg Forsikring", status="unresolved", found_via="jobindex")
    b = companies.Company(name="Tryg Forsikring A/S", status="unresolved", found_via="linkedin")
    items = [a, b]
    assert companies.merge(items, "Tryg Forsikring A/S", "Tryg Forsikring") is b
    assert items == [b] and b.aliases == ["Tryg Forsikring"] or items == [b]


@pytest.mark.parametrize("entry, name", [
    ("karrier.acme.hu", "Acme"),          # Hungarian career host label, from i18n/country/hu.toml
    ("acme.karrier.hu", "Acme"),          # ... also where it is the registrable label
    ("careers.acme.co.uk", "Acme"),
    ("acme.allas.hu", "Acme"),
    ("www.acme.dk", "Acme"),
])
def test_guess_name_skips_every_countrys_generic_host_labels(entry, name):
    assert companies.guess_name(entry) == name


def test_guess_name_skips_a_new_countrys_career_host_label(monkeypatch):
    from door import i18n

    zz = i18n.CountryPack(code="zz", name="Zz", career_hosts=["xyz"])
    monkeypatch.setattr(i18n, "countries", lambda: {"zz": zz})
    assert companies.guess_name("xyz.acme.zz") == "Acme"
    assert companies.guess_name("acme.xyz.zz") == "Acme"


# --------------------------------------------------------------------------- #
# a platform's own host is never the employer's name, and two feeds are two entries (#436)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("entry, name", [
    ("https://dca.career.emply.com/en", "Dca"),
    ("https://rodekors.career.emply.com/en", "Rodekors"),
    ("https://novonordisk.wd3.myworkdayjobs.com", "Novonordisk"),
    ("https://wd3.myworkdaysite.com/recruiting/acme/External", "Acme"),
    ("ramboll3", "Ramboll"),
    ("https://eeho.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1", "Eeho"),
    ("https://acme.teamtailor.com", "Acme"),
    ("kpmg.dk", "Kpmg"),
    ("https://kk.signatur.dk/job/1", "Kk"),
    ("3shape", "3shape"),
])
def test_guess_name_takes_the_tenant_on_a_platforms_host(entry, name):
    assert companies.guess_name(entry) == name


def test_no_guessed_name_is_a_platforms_host_label():
    from door.core import ats_detect

    labels = {d.split(".")[0] for d in ats_detect.platform_domains()}
    assert {"emply", "myworkdayjobs", "oraclecloud", "smartrecruiters", "teamtailor"} <= labels
    for domain in ats_detect.platform_domains():
        assert companies.guess_name(f"https://careers.{domain}/x").lower() not in labels
        assert companies.guess_name(f"https://acme.{domain}/x") == "Acme"


@pytest.mark.parametrize("html, name", [
    ('<meta property="og:site_name" content="Dansk Røde Kors">', "Dansk Røde Kors"),
    ('<script type="application/ld+json">{"@type": "JobPosting", "hiringOrganization": '
     '{"@type": "Organization", "name": "DanChurchAid"}}</script>', "DanChurchAid"),
    ("<title>Ledige stillinger | KPMG Danmark</title>", "KPMG Danmark"),
    ("<title>Careers at Ørsted</title>", "Ørsted"),
    ("<title>International positions I DanchurchAid</title>", "DanchurchAid"),  # Emply's separator
    ("<title>Career I R&#248;de Kors</title>", "Røde Kors"),
    ("<title>Ørsted - Careers</title>", "Ørsted"),
    ('<meta property="og:site_name" content="Emply"><title>Emply</title>', ""),
    ('<meta property="og:site_name" content="Workday">', ""),
    ("<title>Careers</title>", ""),
    ("<title>Lediga anställningar vid Karolinska Institutet</title>", "Karolinska Institutet"),  # Varbi's (#525)
    ("<title>Lediga jobb hos Kungliga Tekniska högskolan</title>", "Kungliga Tekniska högskolan"),
    ("<title>Arbetsgivarverket |  </title>", "Arbetsgivarverket"),  # ReachMee's empty list (#527)
    ("<title>\u00d6rebro universitet | Lediga jobb</title>", "\u00d6rebro universitet"),
    ("<p>no name here</p>", ""),
])
def test_name_from_page_reads_what_the_page_calls_its_employer(html, name):
    assert companies.name_from_page(html) == name


def test_one_name_on_two_feeds_is_two_entries_flagged_for_merging():
    items: list = []
    dca, _ = companies.record(items, "Emply", feed=("career_sites", "https://dca.career.emply.com"),
                              status="followed", found_via="manual", now=NOW)
    rk, is_new = companies.record(items, "Emply", feed=("career_sites", "https://rodekors.career.emply.com"),
                                  status="followed", found_via="manual", now=NOW)
    assert is_new and len(items) == 2 and rk is not dca
    assert dca.feed.id == "https://dca.career.emply.com" and rk.feed.id == "https://rodekors.career.emply.com"
    assert companies.merge_candidates(items) == [{"names": ["Emply", "Emply"], "reason": "same name"}]


def test_a_named_entry_with_a_feed_still_takes_a_miss_and_the_same_feed():
    items: list = []
    companies.record(items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual", now=NOW)
    companies.record(items, "Acme", feed=None, status="unresolved", reason="x", found_via="jobindex", now=NOW)
    companies.record(items, "acme", feed=("lever", "Acme"), status="followed", found_via="jobindex", now=NOW)
    assert len(items) == 1 and items[0].feed.id.lower() == "acme"


# --- refusal (#438): "must not" and "can't yet" are declared, not read from the reason text ---

def test_an_unfollowable_company_keeps_why_it_is_not_followed(tmp_path):
    items = []
    companies.record(items, "Dalux", feed=None, status="unfollowable", found_via="manual", reason="HR-ON", refusal="must_not", now=NOW)
    companies.record(items, "Genmab", feed=None, status="unfollowable", found_via="manual", reason="Phenom", refusal="cant_yet", now=NOW)
    companies.save(tmp_path, items)

    assert [c.refusal for c in companies.load(tmp_path)] == ["must_not", "cant_yet"]
    assert json.loads((tmp_path / "companies.json").read_text())["companies"][0]["refusal"] == "must_not"


def test_an_old_file_without_a_refusal_loads_unchanged(tmp_path):
    _write(tmp_path, [{"name": "X", "status": "unfollowable", "reason": "r", "found_via": "manual"}])
    assert companies.load(tmp_path)[0].refusal is None


def test_a_refusal_must_be_one_of_the_two_kinds():
    with pytest.raises(ValueError):
        companies.Company(name="X", status="unfollowable", found_via="manual", refusal="whatever")


def test_a_followed_result_clears_the_refusal():
    items = []
    companies.record(items, "Genmab", feed=None, status="unfollowable", found_via="manual", refusal="cant_yet", now=NOW)
    company, _ = companies.record(items, "Genmab", feed=("greenhouse", "genmab"), status="followed", found_via="manual", now=NOW)
    assert company.refusal is None
# --------------------------------------------------------------------------- #
# an employer followed through career_sites on an Emply host moves to the emply feed (#437)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("old", ["https://dca.career.emply.com", "dca.career.emply.com", "https://dca.career.emply.com/en"])
def test_a_career_sites_entry_on_an_emply_host_loads_as_the_emply_feed(old):
    company = companies.Company.model_validate(
        {"name": "DanChurchAid", "feed": {"platform": "career_sites", "id": old}, "status": "followed",
         "found_via": "manual"})
    assert (company.feed.platform, company.feed.id) == ("emply", "dca")


def test_other_career_sites_entries_are_left_alone():
    company = companies.Company.model_validate(
        {"name": "Acme", "feed": {"platform": "career_sites", "id": "https://careers.acme.example"},
         "status": "followed", "found_via": "manual"})
    assert (company.feed.platform, company.feed.id) == ("career_sites", "https://careers.acme.example")


def test_the_upgrade_is_written_on_the_next_save(tmp_path):
    (tmp_path / companies.FILENAME).write_text(json.dumps({"version": companies.VERSION, "companies": [
        {"name": "DanChurchAid", "feed": {"platform": "career_sites", "id": "https://dca.career.emply.com"},
         "status": "followed", "found_via": "manual"}]}), encoding="utf-8")
    items = companies.load(tmp_path)
    companies.save(tmp_path, items)
    saved = json.loads((tmp_path / companies.FILENAME).read_text(encoding="utf-8"))
    assert saved["companies"][0]["feed"] == {"platform": "emply", "id": "dca"}


def test_a_collect_problem_is_stamped_and_cleared():
    items: list = []
    acme, _ = companies.record(items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual", now=NOW)

    companies.set_collect_problem(acme, "blocked", "bot protection", NOW)
    assert (acme.collect_problem.outcome, acme.collect_problem.reason, acme.collect_problem.at) == (
        "blocked", "bot protection", NOW)
    assert companies.Company.model_validate(acme.model_dump()).collect_problem == acme.collect_problem

    companies.set_collect_problem(acme, None, "", NOW)
    assert acme.collect_problem is None


def test_recording_a_follow_clears_an_old_collect_problem():
    items: list = []
    acme, _ = companies.record(items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual", now=NOW)
    companies.set_collect_problem(acme, "failed", "x", NOW)

    companies.record(items, "Acme", feed=("lever", "acme"), status="followed", found_via="manual", now=NOW)

    assert companies.find(items, "Acme").collect_problem is not None  # unchanged: only collect clears it
