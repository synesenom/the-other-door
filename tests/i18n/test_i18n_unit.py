"""Unit tests for src/door/i18n: the language and country data files and the
helpers the matching passes build their word lists from."""

import os

import pytest
from pydantic import ValidationError

from door import i18n


# ---------------------------------------------------------------------------
# The data files
# ---------------------------------------------------------------------------


def test_every_language_file_loads_under_its_own_code():
    packs = i18n.languages()
    assert {"en", "da"} <= set(packs)
    for code, pack in packs.items():
        assert pack.code == code


def test_every_country_file_loads_and_names_known_languages():
    countries = i18n.countries()
    assert "dk" in countries
    for code, country in countries.items():
        assert country.code == code
        for lang in country.languages:
            assert lang in i18n.languages(), f"{code}.toml names unknown language {lang!r}"


def test_a_language_file_with_an_unknown_key_is_rejected(tmp_path):
    bad = tmp_path / "xx.toml"
    bad.write_text('code = "xx"\nname = "X"\nsurprise = 1\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


def test_a_seniority_level_outside_the_canonical_set_is_rejected(tmp_path):
    bad = tmp_path / "xx.toml"
    bad.write_text('code = "xx"\nname = "X"\n[seniority]\nboss = ["boss"]\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


def test_a_star_anywhere_but_the_end_is_rejected(tmp_path):
    bad = tmp_path / "xx.toml"
    bad.write_text('code = "xx"\nname = "X"\nnames = ["*x"]\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


# ---------------------------------------------------------------------------
# word_pattern
# ---------------------------------------------------------------------------


def test_word_pattern_matches_whole_words_only():
    rx = i18n.compile_words(["intern"])
    assert rx.search("Summer intern wanted")
    assert not rx.search("international team")
    assert not rx.search("internal tools")


def test_word_pattern_star_matches_a_prefix():
    rx = i18n.compile_words(["dansk*"])
    assert rx.search("Gode danskkundskaber")
    assert rx.search("Du taler dansk.")
    assert not rx.search("udansk")


def test_word_pattern_handles_punctuation_in_a_word():
    rx = i18n.compile_words(["kr.", "on-site"])
    assert rx.search("Løn 45.000 kr. om måneden")
    assert rx.search("Fully on-site role")


def test_word_pattern_of_nothing_matches_nothing():
    assert not i18n.compile_words([]).search("anything at all")


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_DANISH = (
    "Vil du være med til at bygge vores dataplatform? Vi søger en erfaren "
    "dataforsker, som har lyst til at arbejde med machine learning og Python."
)
_ENGLISH = (
    "We are looking for an experienced data scientist who will join our team "
    "and work with machine learning in Python."
)


_SWEDISH = (
    "Vi söker en erfaren data scientist som har erfarenhet av Python och "
    "maskininlärning. Du kommer att arbeta med vårt team på kontoret i Stockholm."
)
_NORWEGIAN = (
    "Vi søker en erfaren dataforsker som har erfaring med Python og maskinlæring. "
    "Du vil jobbe med teamet vårt på kontoret i Oslo, og det er viktig at du trives."
)
_FINNISH = (
    "Etsimme kokenutta data scientistia, jolla on kokemusta Pythonista ja "
    "koneoppimisesta. Työskentelet tiimissämme Helsingin toimistolla."
)


@pytest.mark.parametrize(
    "text, code",
    [(_DANISH, "da"), (_ENGLISH, "en"), (_SWEDISH, "sv"), (_NORWEGIAN, "no"), (_FINNISH, "fi")],
)
def test_detect_language(text, code):
    """Including the Scandinavian languages, which share most short words,
    and languages without a data file."""
    assert i18n.detect_language(text) == code


def test_detect_language_reports_norwegian_as_no_whatever_the_written_standard():
    nynorsk = "Vi søkjer ein røynd dataforskar som har erfaring med Python. Du vil jobbe i teamet vårt i Bergen."
    assert i18n.detect_language(nynorsk) == "no"


@pytest.mark.parametrize("text", ["", "Data Scientist"])
def test_detect_language_returns_none_without_enough_evidence(text):
    assert i18n.detect_language(text) is None


# ---------------------------------------------------------------------------
# Country helpers
# ---------------------------------------------------------------------------


def test_city_names_for_an_english_city_include_its_danish_names():
    names = i18n.city_names("Copenhagen")
    assert "københavn*" in names
    assert "kastrup" in names


def test_city_names_for_a_danish_city_include_its_english_name():
    assert "copenhagen" in i18n.city_names("København")


def test_city_names_accepts_a_location_with_a_country_suffix():
    assert "københavn*" in i18n.city_names("Copenhagen, Denmark")


def test_city_names_of_an_unknown_city_is_empty():
    assert i18n.city_names("Springfield") == []


def test_legal_suffixes_cover_danish_and_international_forms():
    suffixes = i18n.legal_suffixes()
    assert {"a/s", "aps", "i/s", "ltd", "gmbh"} <= set(suffixes)


def test_slug_suffixes_carry_the_international_extras_from_common_toml():
    extras = {"limited", "inc", "plc", "llc", "bv", "nv", "group", "holding", "nordic", "ab", "oy", "ag", "sa",
              "as", "asa", "a/s", "gmbh", "ltd"}
    assert extras <= set(i18n.slug_suffixes())
    assert "group" not in i18n.legal_suffixes()   # dedup compares names with the legal forms only


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------


def test_seniority_words_map_to_canonical_levels():
    words = i18n.seniority_words()
    assert words["senior"] == "senior"
    assert words["ledende"] == "lead"


def test_academic_ranks_are_one_level_in_english_and_danish():
    words = i18n.seniority_words()
    for rank in ("postdoc", "postdoctoral", "assistant professor", "associate professor", "professor",
                 "adjunkt", "lektor", "tenure track", "tenure-track"):
        assert words[rank] == "academic", rank
    assert "assistant" not in words and "associate" not in words   # only as the phrases


def test_marker_words_are_the_union_over_languages():
    remote = i18n.marker_words("remote")
    assert "remote" in remote
    assert "hjemmearbejde" in remote


def test_heading_words_include_danish_headings():
    assert "om stillingen" in i18n.heading_words("responsibility")
    assert "om virksomheden" in i18n.heading_words("drop")
    assert "hvem er du" in i18n.heading_words("requirement")


def test_language_names_name_danish_in_both_languages():
    names = i18n.language_names()
    assert "danish" in names and "dansk*" in names


def test_the_supported_languages_are_the_language_files():
    """The languages with full word lists; profile `languages` may only name these.
    Adding a language is a new file, so this only pins the ones there today."""
    assert {"en", "da"} <= set(i18n.languages())
    assert set(i18n.languages()) == {p.stem for p in i18n.LANG_DIR.glob("*.toml")}


@pytest.mark.parametrize("value, code", [("English", "en"), ("DA", "da"), (" en ", "en")])
def test_language_code_accepts_a_supported_name_or_code(value, code):
    assert i18n.language_code(value) == code


@pytest.mark.parametrize("value", ["Klingon", ""])
def test_language_code_of_an_unsupported_language_is_none(value):
    assert i18n.language_code(value) is None


def test_language_label_names_a_supported_language():
    assert i18n.language_label("da") == "Danish (da)"


def test_language_label_falls_back_to_the_code_or_unknown():
    assert i18n.language_label("tlh") == "tlh"
    assert i18n.language_label(None) == "unknown"


def test_false_friends_are_per_language():
    assert "intern" in i18n.false_friends("da")
    assert i18n.false_friends("en") == []
    assert i18n.false_friends(None) == []


def test_transliteration_spells_danish_letters_out():
    table = i18n.transliteration()
    assert "Ærø Å".translate(table) == "aeroe aa"


def test_supported_language_names_list_english_first():
    names = i18n.supported_language_names().split(", ")
    assert names[0] == "English"
    assert "Danish" in names
    assert sorted(names) == sorted(p.name for p in i18n.languages().values())


def test_country_for_location_finds_the_city_or_an_alias():
    assert i18n.country_for_location("Copenhagen").name == "Denmark"
    assert i18n.country_for_location("Frederiksberg, Denmark").name == "Denmark"
    assert i18n.country_for_location("Atlantis") is None
    assert i18n.country_for_location("") is None


def test_known_cities_are_title_cased_with_their_country():
    cities = i18n.known_cities()
    assert ("Copenhagen", "Denmark") in cities
    assert ("Aarhus", "Denmark") in cities


def _pack(code, **fields):
    return i18n.LanguagePack(code=code, name=code.upper(), **fields)


def test_language_files_may_not_spell_a_letter_differently():
    """The transliteration table is shared by every language, so two spellings of one letter conflict."""
    packs = {"de": _pack("de", transliterate={"ö": "oe"}), "sv": _pack("sv", transliterate={"ö": "o"})}
    with pytest.raises(ValueError, match="ö"):
        i18n._check_conflicts(packs)


def test_language_files_may_not_map_a_seniority_word_to_two_levels():
    packs = {"da": _pack("da", seniority={"head": ["chef"]}), "fr": _pack("fr", seniority={"manager": ["chef"]})}
    with pytest.raises(ValueError, match="chef"):
        i18n._check_conflicts(packs)


def test_agreeing_language_files_do_not_conflict():
    packs = {"a": _pack("a", seniority={"senior": ["senior*"]}), "b": _pack("b", seniority={"senior": ["Senior*"]})}
    i18n._check_conflicts(packs)


def test_the_language_files_do_not_conflict():
    i18n._check_conflicts(i18n.languages())


@pytest.mark.parametrize("location", ["Denmark", "Danmark", "Remote, Denmark"])
def test_country_for_location_finds_the_country_by_name(location):
    assert i18n.country_for_location(location).code == "dk"


def test_scope_is_the_ads_language_plus_english():
    """English terms turn up in ads in every language; other languages' words don't."""
    assert i18n.scope("da") == ("da", "en")
    assert i18n.scope("en") == ("en",)


@pytest.mark.parametrize("code", [None, "tlh"])
def test_scope_of_an_unknown_language_is_every_language(code):
    assert i18n.scope(code) is None


def test_word_lists_can_be_scoped_to_languages():
    assert "om os" in i18n.heading_words("drop")
    assert "om os" not in i18n.heading_words("drop", ("en",))
    assert "løn*" not in i18n.marker_words("salary", ("en",))
    assert "chef" in i18n.seniority_words() and "chef" not in i18n.seniority_words(("en",))


# ---------------------------------------------------------------------------
# Stop words and URL-slug spellings (career_sites ranking, issue #257)
# ---------------------------------------------------------------------------


def test_stop_words_are_the_filler_words_of_every_language():
    words = i18n.stop_words()
    assert {"and", "of", "og", "til"} <= set(words)
    assert "data" not in words


def test_stop_words_can_be_limited_to_a_language():
    assert "og" not in i18n.stop_words(("en",))
    assert "og" in i18n.stop_words(("da",))


def test_slug_forms_cover_the_ways_urls_fold_special_letters():
    forms = i18n.slug_forms("Hørsholm")
    assert {"hrsholm", "horsholm", "hoersholm"} <= set(forms)
    assert {"kobenhavn", "kbenhavn", "koebenhavn"} <= set(i18n.slug_forms("København"))
    assert {"aarhus", "arhus"} <= set(i18n.slug_forms("Århus"))
    assert i18n.slug_forms("Copenhagen") == ["copenhagen"]


# ---------------------------------------------------------------------------
# Words of a careers listing (the career-site fallback)
# ---------------------------------------------------------------------------


def test_path_stems_name_a_job_page_in_every_language():
    stems = i18n.career_path_stems()
    assert {"job", "roles", "vacanc", "position", "stilling", "karriere", "ledige"} <= set(stems)
    assert "stilling" not in i18n.career_path_stems(("en",))


def test_nav_words_are_links_of_a_listing_that_are_not_ads():
    words = i18n.career_nav_words()
    assert {"all jobs", "next", "alle job", "næste"} <= set(words)


def test_apply_words_are_the_link_texts_that_start_an_application():
    words = i18n.career_apply_words()
    assert {"apply", "apply now", "ansøg", "ansøg nu"} <= set(words)
    assert "ansøg" not in i18n.career_apply_words(("en",))


def test_job_id_parameters_are_common_to_every_language():
    assert {"career_job_req_id", "jobid"} <= set(i18n.job_id_params())


def test_synonyms_are_groups_of_equivalent_terms():
    groups = i18n.synonyms()
    assert any("artificial intelligence" in g and "ai" in g for g in groups)
    assert any("machine learning" in g and "ml" in g for g in groups)
    assert any("human resources" in g and "hr" in g for g in groups)


# ---------------------------------------------------------------------------
# Country data for employer feed detection (#289)
# ---------------------------------------------------------------------------

def test_slug_spellings_put_the_spelled_out_form_first_and_forms_end_with_the_dropped_letter():
    assert i18n.slug_spellings("Hørsholm") == ["hoersholm", "horsholm"]
    assert i18n.slug_spellings("Müller") == ["mueller", "muller"]
    assert i18n.slug_forms("Hørsholm") == ["hoersholm", "horsholm", "hrsholm"]


def test_a_country_pack_accepts_tlds_career_hosts_and_job_boards():
    pack = i18n.CountryPack(code="zz", name="Zz", tlds=["ZZ"], career_hosts=["Karrier"], job_boards=["Jobs.Example"])
    assert (pack.tlds, pack.career_hosts, pack.job_boards) == (["zz"], ["karrier"], ["jobs.example"])
    bare = i18n.CountryPack(code="zz", name="Zz")
    assert (bare.tlds, bare.career_hosts, bare.job_boards) == ([], [], [])


@pytest.mark.parametrize("key", ["tlds", "career_hosts", "job_boards"])
def test_a_country_pack_rejects_a_bad_word_in_the_new_keys(key):
    with pytest.raises(ValidationError):
        i18n.CountryPack(code="zz", name="Zz", **{key: [" "]})


def test_a_country_pack_still_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        i18n.CountryPack(code="zz", name="Zz", surprise=["x"])


def test_generic_host_labels_cover_the_common_fixed_labels_career_words_and_every_countrys_hosts(monkeypatch):
    zz = i18n.CountryPack(code="zz", name="Zz", career_hosts=["xyz"])
    monkeypatch.setattr(i18n, "countries", lambda: {"zz": zz})
    labels = set(i18n.generic_host_labels())
    assert {"www", "apply", "boards", "recruiting", "careers", "jobs", "karriere", "xyz"} <= labels
    assert not [label for label in labels if " " in label]   # one-word labels only


def test_generic_host_labels_include_the_ascii_form_of_a_word_with_accents():
    assert {"allas", "karrier"} <= set(i18n.generic_host_labels())


def test_tld_labels_are_every_countrys_tlds_and_the_global_ones(monkeypatch):
    zz = i18n.CountryPack(code="zz", name="Zz", tlds=["zz"])
    monkeypatch.setattr(i18n, "countries", lambda: {"zz": zz})
    assert set(i18n.tld_labels()) == {"zz", "com", "net", "org", "io", "eu", "co"}


def test_job_board_domains_are_the_union_of_the_countries(monkeypatch):
    a = i18n.CountryPack(code="aa", name="A", job_boards=["a.example"])
    b = i18n.CountryPack(code="bb", name="B", job_boards=["b.example", "a.example"])
    monkeypatch.setattr(i18n, "countries", lambda: {"aa": a, "bb": b})
    assert i18n.job_board_domains() == ["a.example", "b.example"]


def test_hungary_and_denmark_carry_their_feed_detection_data():
    countries = i18n.countries()
    assert countries["hu"].tlds == ["hu"] and {"karrier", "allas"} <= set(countries["hu"].career_hosts)
    assert countries["dk"].tlds == ["dk"] and {"karriere", "job"} <= set(countries["dk"].career_hosts)
    assert "profession.hu" in i18n.job_board_domains()


def test_sweden_carries_its_feed_detection_data_and_names():
    se = i18n.countries()["se"]
    assert se.tlds == ["se"] and {"karriar", "jobb"} <= set(se.career_hosts)
    assert {"arbetsformedlingen.se", "jobbsafari.se"} <= set(i18n.job_board_domains())
    assert se.languages == ["sv"] and {"ab", "aktiebolag", "hb", "kb"} <= set(se.legal_suffixes)
    assert {"kr", "sek", "kronor", "tkr", "mkr"} <= {w.lower() for w in se.currency}
    for location in ("Sweden", "Sverige", "Remote, Sweden"):
        assert i18n.country_for_location(location).code == "se"
    for city in ("Gothenburg", "Göteborg", "Goteborg", "Malmo", "Solna", "Uppsala"):
        assert i18n.country_for_location(city).code == "se", city
    assert i18n.country_for_location("Copenhagen").code == "dk"


def test_swedish_is_a_supported_language_with_synonyms():
    assert "sv" in i18n.languages() and i18n.language_code("Swedish") == "sv"
    groups = [set(g) for g in i18n.synonyms()]
    assert any({"ai", "artificiell intelligens"} <= g for g in groups)
    assert any({"ml", "maskininlärning"} <= g for g in groups)
    assert "och" in i18n.stop_words(("sv",))


# ---------------------------------------------------------------------------
# [work_permit]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["en", "da"])
@pytest.mark.parametrize("key", ["no_sponsorship", "permit_required", "sponsorship_offered"])
def test_en_and_da_carry_work_permit_phrases(code, key):
    assert getattr(i18n.languages()[code].work_permit, key)


@pytest.mark.parametrize(
    "body",
    [
        'no_sponsorship = [""]',
        'surprise = ["x"]',
        'permit_required = ["a*b"]',
    ],
)
def test_a_bad_work_permit_section_is_rejected(tmp_path, body):
    bad = tmp_path / "xx.toml"
    bad.write_text(f'code = "xx"\nname = "X"\n[work_permit]\n{body}\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


def test_work_permit_phrases_by_language_name():
    phrases = i18n.work_permit_phrases()
    assert list(phrases)[:2] == ["English", "Danish"] or {"English", "Danish"} <= set(phrases)
    assert "kan ikke tilbyde sponsorering" in phrases["Danish"].no_sponsorship


def test_work_permit_words_union_over_every_language():
    words = i18n.work_permit_words()
    assert "unable to offer visa sponsorship" in words
    assert "kan ikke tilbyde sponsorering" in words
    assert len(words) == len(set(words))
    assert all(w == w.lower() for w in words)


@pytest.mark.parametrize(
    "kind,text",
    [
        ("no_sponsorship", "No sponsorship needed for EU citizens."),
        ("no_sponsorship", "There is no sponsorship budget for events."),
        ("permit_required", "You must already hold a degree in finance."),
        ("permit_required", "We value the right to work in a team."),
        ("permit_required", "You are eligible to work in hybrid mode."),
        ("sponsorship_offered", "Sponsorship available for our meetup."),
    ],
)
def test_work_permit_phrases_do_not_match_unrelated_sentences(kind, text):
    pattern = i18n.compile_words(
        {w for pack in i18n.languages().values() for w in getattr(pack.work_permit, kind)}
    )
    assert not pattern.search(text)


# ---------------------------------------------------------------------------
# [injection]: phrases that mark an ad line as addressed to a model
# ---------------------------------------------------------------------------


def test_injection_phrases_union_over_every_language():
    phrases = i18n.injection_phrases()
    assert "ignore previous instructions" in phrases["instruction"]
    assert "ignorer tidligere instruktioner" in phrases["instruction"]
    assert phrases["score_request"]
    assert all(p == p.lower() for kind in phrases.values() for p in kind)


@pytest.mark.parametrize("body", ['instruction = [""]', 'surprise = ["x"]', 'score_request = ["a*b"]'])
def test_a_bad_injection_section_is_rejected(tmp_path, body):
    bad = tmp_path / "xx.toml"
    bad.write_text(f'code = "xx"\nname = "X"\n[injection]\n{body}\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


def test_a_language_file_without_injection_loads(tmp_path):
    ok = tmp_path / "xx.toml"
    ok.write_text('code = "xx"\nname = "X"\n')
    assert i18n.load_language_file(ok).injection.instruction == []


# ---------------------------------------------------------------------------
# CV section titles and skill stop words (facts check, issue #369)
# ---------------------------------------------------------------------------


def test_cv_section_titles_cover_english_and_danish():
    assert {"skills", "kompetencer"} <= set(i18n.cv_section("skills"))
    assert {"education", "uddannelse"} <= set(i18n.cv_section("education"))
    assert {"certifications", "certificeringer"} <= set(i18n.cv_section("certifications"))


def test_cv_section_of_an_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        i18n.cv_section("hobbies")


def test_skill_stop_words_are_generic_words_of_every_language():
    words = set(i18n.skill_stop_words())
    assert {"communication", "kommunikation", "january", "monday"} <= words
    assert "terraform" not in words


# ---------------------------------------------------------------------------
# Compounds, plurals and role nouns (#428)
# ---------------------------------------------------------------------------


def test_the_compounding_languages_are_flagged():
    assert i18n.compounding_codes() == {"da", "hu", "sv"}


def test_plural_suffixes_come_from_the_language_files():
    assert set(i18n.plural_suffixes(("en",))) == {"s", "es"}
    assert {"er", "e", "r"} <= set(i18n.plural_suffixes(("da",)))
    assert {"k", "ak", "ek", "ok", "ök"} <= set(i18n.plural_suffixes(("hu",)))
    assert "er" in i18n.plural_suffixes() and "s" in i18n.plural_suffixes()


def test_role_nouns_are_the_generic_words_of_a_title():
    en = set(i18n.role_nouns(("en",)))
    assert {"manager", "partner", "specialist", "officer", "advisor", "consultant", "management", "total",
            "coordinator", "assistant"} <= en
    assert {"konsulent", "rådgiver", "medarbejder", "ansvarlig"} <= set(i18n.role_nouns(("da",)))
    assert "nurse" not in en and "sygeplejerske" not in i18n.role_nouns()


def test_language_codes_map_names_and_default_to_english():
    assert i18n.language_codes(["English", "danish", "Klingon"]) == ("en", "da")
    assert i18n.language_codes([]) == ("en",)
    assert i18n.language_codes(None) == ("en",)


def test_a_plural_suffix_with_a_star_is_rejected(tmp_path):
    bad = tmp_path / "xx.toml"
    bad.write_text('code = "xx"\nname = "X"\nplural_suffixes = ["s*"]\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


def test_compounds_must_be_a_boolean(tmp_path):
    bad = tmp_path / "xx.toml"
    bad.write_text('code = "xx"\nname = "X"\ncompounds = "yes"\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


def test_role_nouns_are_checked_like_other_word_lists(tmp_path):
    bad = tmp_path / "xx.toml"
    bad.write_text('code = "xx"\nname = "X"\nrole_nouns = ["*x"]\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


# ---------------------------------------------------------------------------
# The commute area (#429)
# ---------------------------------------------------------------------------


def test_commute_names_of_copenhagen_include_the_towns_an_hour_away():
    names = i18n.commute_names("Copenhagen")
    assert {"hillerød", "roskilde", "køge"} <= set(names)
    assert i18n.commute_names("København") == names


def test_commute_names_of_a_city_without_a_commute_area_is_empty():
    assert i18n.commute_names("Odense") == []
    assert i18n.commute_names("Springfield") == []


def test_every_commute_key_is_a_city_of_the_same_file():
    for pack in i18n.countries().values():
        assert set(pack.commute) <= set(pack.cities), pack.code


def test_a_commute_key_that_is_not_a_city_is_refused():
    with pytest.raises(ValidationError):
        i18n.CountryPack(code="xx", name="Xland", cities={"a": []}, commute={"b": ["c"]})


def test_place_names_cover_cities_commute_towns_and_foreign_places():
    places = i18n.compile_words(i18n.place_names())
    for place in ("Aarhus", "Hillerød", "Berlin, Germany", "Stockholm", "Denmark"):
        assert places.search(place), place
    assert not places.search("Rigshospitalet")


# ---------------------------------------------------------------------------
# France (country/fr.toml, lang/fr.toml)
# ---------------------------------------------------------------------------


def test_french_is_a_supported_language_and_france_names_it():
    assert "fr" in i18n.languages()
    assert i18n.language_code("French") == "fr" and i18n.language_code("fr") == "fr"
    assert i18n.countries()["fr"].languages == ["fr"]
    assert "French" in i18n.supported_language_names().split(", ")


def test_france_carries_its_currency_company_forms_hosts_and_boards():
    fr = i18n.countries()["fr"]
    assert {"€", "eur", "euro", "euros"} <= set(fr.currency)
    assert {"sas", "sarl", "sasu", "eurl", "sa", "scop"} <= set(fr.legal_suffixes)
    assert fr.tlds == ["fr"] and "carrieres" in fr.career_hosts
    assert {"francetravail.fr", "hellowork.com", "choisirleservicepublic.gouv.fr"} <= set(fr.job_boards)
    assert fr.name == "France" and "république française" in fr.names


def test_the_french_seniority_words_map_to_canonical_levels():
    levels = i18n.seniority_words(("fr",))
    for word in ("junior*", "débutant*", "stagiaire*", "stage", "alternan*", "apprenti", "apprentie"):
        assert levels[word] == "junior", word
    assert levels["senior*"] == "senior" and levels["directeur"] == "head" and levels["responsable"] == "manager"
    assert levels["maître de conférences"] == "academic" and levels["postdoctorant*"] == "academic"


def test_a_bare_chef_is_no_head_and_confirme_has_no_level():
    levels = i18n.seniority_words(("fr",))
    assert "chef" not in levels and "confirmé" not in levels and "confirme" not in levels
    assert levels["chef d'équipe"] == "manager"


def test_french_apostrophes_are_written_in_both_forms():
    """The matching code does not fold ’ into ': a word with an apostrophe is listed with each."""
    pack = i18n.languages()["fr"]
    words = [*pack.markers.requirement, *pack.seniority["manager"], *pack.careers.link]
    straight = {w for w in words if "'" in w}
    assert straight
    for word in straight:
        assert word.replace("'", "’") in words, word
    assert i18n.compile_words(pack.markers.requirement).search("3 ans d’expérience minimum")
    assert i18n.compile_words(pack.markers.requirement).search("3 ans d'expérience minimum")


def test_french_letters_fold_to_ascii_and_agree_with_the_other_languages():
    table = i18n.transliteration()
    assert "œuvre".translate(table) == "oeuvre"
    assert i18n.slug_spellings("Cœur Défense")[0] == "coeur defense"
    assert i18n.slug_spellings("Müller")[0] == "mueller"   # the German spelling stays common.toml's
    assert i18n.slug_spellings("Île-de-France")[0] == "ile-de-france"
    i18n.languages()   # raises when two files disagree on a letter or a seniority word


def test_french_stop_words_are_listed_with_and_without_the_accent_and_elision_letters():
    stops = i18n.stop_words(("fr",))
    assert {"de", "du", "des", "la", "le", "les", "pour", "et", "à", "d", "l"} <= set(stops)


def test_french_months_are_numbered_and_validated(tmp_path):
    months = i18n.month_numbers(("fr",))
    assert months["janvier"] == 1 and months["août"] == 8 and months["aout"] == 8
    assert months["décembre"] == 12 and months["févr."] == 2 and months["sept."] == 9
    assert set(months.values()) == set(range(1, 13))
    assert i18n.month_numbers(("da",)) == {}
    for body in ('months = {janvier = 13}', 'months = {janvier = 1}'):
        bad = tmp_path / "xx.toml"
        bad.write_text(f'code = "xx"\nname = "X"\n{body}\n')
        with pytest.raises(ValidationError):
            i18n.load_language_file(bad)   # a month out of 1..12, or a table that leaves months out


def test_french_month_names_and_weekdays_are_not_skills():
    stops = set(i18n.skill_stop_words(("fr",)))
    assert {"janvier", "octobre", "lundi", "dimanche", "rigueur", "autonomie"} <= stops


def test_a_french_synonym_is_on_topic_through_common_toml():
    groups = [g for g in i18n.synonyms() if "ai" in g]
    assert any("intelligence artificielle" in g for g in groups)
    assert any("apprentissage automatique" in g for g in i18n.synonyms() if "ml" in g)


def test_france_has_the_big_cities_with_their_suburbs_and_commute_towns():
    names = i18n.city_names("Paris, France")
    assert {"paris*", "la défense", "boulogne-billancourt", "île-de-france"} <= set(names)
    assert "villeurbanne" in i18n.city_names("Lyon")
    assert "nanterre" in i18n.city_names("Paris")
    assert "massy" in i18n.commute_names("Paris") and "cergy" in i18n.commute_names("Paris")
    assert i18n.country_for_location("Marseille").code == "fr"
    assert i18n.country_for_location("France").code == "fr"
    assert set(i18n.countries()["fr"].commute) <= set(i18n.countries()["fr"].cities)


# ---------------------------------------------------------------------------
# title_tags: the gender tags a job title carries ("H/F", "(m/k)")
# ---------------------------------------------------------------------------


def test_title_tags_are_read_from_the_language_files():
    tags = [t.lower() for t in i18n.title_tags()]
    assert {"h/f", "f/h", "h/f/x", "f/h/x", "m/f", "f/m"} <= set(tags)
    assert "m/k" in tags  # Danish


@pytest.mark.parametrize("tag", ["HF", "H/F*", "/F", "H//F", " "])
def test_a_title_tag_that_is_not_letters_split_by_a_slash_or_a_dot_is_rejected(tmp_path, tag):
    bad = tmp_path / "xx.toml"
    bad.write_text(f'code = "xx"\nname = "X"\ntitle_tags = ["{tag}"]\n')
    with pytest.raises(ValidationError):
        i18n.load_language_file(bad)


@pytest.mark.parametrize("title, clean", [
    ("Comptable H/F", "Comptable"),
    ("Comptable F/H", "Comptable"),
    ("Comptable (H/F)", "Comptable"),
    ("Comptable (h/f)", "Comptable"),
    ("Comptable [H/F]", "Comptable"),
    ("Comptable - H/F", "Comptable"),
    ("Comptable – F/H", "Comptable"),
    ("Comptable H/F/X", "Comptable"),
    ("Comptable (F/H/X)", "Comptable"),
    ("Comptable (F/M/X)", "Comptable"),
    ("Comptable M/F", "Comptable"),
    ("Comptable ( H / F )", "Comptable"),
    ("Infirmier de nuit 12H (f.h)", "Infirmier de nuit 12H"),
    ("(H/F) Comptable", "Comptable"),
    ("H/F - Comptable", "Comptable"),
    ("Chef de service (h/f) - Département du Val-de-Marne", "Chef de service - Département du Val-de-Marne"),
    ("Infirmier Chirurgie orthopédique 12h JOUR F/H - Hôpital COCHIN", "Infirmier Chirurgie orthopédique 12h JOUR - Hôpital COCHIN"),
    ("Infirmier Médecine Intensive Réanimation (MIR) F/H F/H", "Infirmier Médecine Intensive Réanimation (MIR)"),
    ("Sygeplejerske (m/k) til akutmodtagelsen", "Sygeplejerske til akutmodtagelsen"),
    ("Data Scientist", "Data Scientist"),
])
def test_strip_title_tags_removes_the_tag_wherever_it_stands(title, clean):
    assert i18n.strip_title_tags(title) == clean


@pytest.mark.parametrize("title", [
    "Ingénieur TH/FX", "Responsable H/Fonction support", "Analyst M/F/D", "Ingénieur IP/AP", "Chef de projet",
    "Sales H/FR team",
])
def test_strip_title_tags_leaves_a_tag_inside_a_word_or_another_tag(title):
    assert i18n.strip_title_tags(title) == title


def test_strip_title_tags_of_a_title_that_is_only_a_tag_keeps_it():
    assert i18n.strip_title_tags("H/F") == "H/F"
    assert i18n.strip_title_tags("") == ""


# ---------------------------------------------------------------------------
# CV conventions per country (#605)
# ---------------------------------------------------------------------------

_SETTLED_CV = {
    "dk": ("optional", False, 2, "DD.MM.YYYY"),
    "fr": ("optional", False, 2, "DD/MM/YYYY"),
    "hu": ("optional", False, 2, "YYYY.MM.DD."),
    "se": ("optional", False, 2, "YYYY-MM-DD"),
    "gb": ("no", False, 2, "DD/MM/YYYY"),
}


@pytest.mark.parametrize("code", sorted(_SETTLED_CV))
def test_each_country_file_settles_its_cv_conventions(code):
    cv = i18n.countries()[code].cv
    assert (cv.photo, cv.date_of_birth, cv.max_pages, cv.date_format) == _SETTLED_CV[code]


def test_every_country_file_has_an_explicit_cv_block():
    import tomllib

    for path in i18n.COUNTRY_DIR.glob("*.toml"):
        assert "cv" in tomllib.loads(path.read_text(encoding="utf-8")), f"{path.name} has no [cv] block"


def test_a_country_without_a_cv_block_gets_the_neutral_default():
    cv = i18n.CountryPack(code="zz", name="Zz").cv
    assert (cv.photo, cv.date_of_birth, cv.max_pages) == ("no", False, 2)


@pytest.mark.parametrize("bad", [
    {"photo": "yes"},
    {"max_pages": 0},
    {"max_pages": 5},
    {"date_format": "DD/MM"},
    {"date_format": "YYYY/YYYY/MM/DD"},
    {"surprise": 1},
])
def test_a_cv_block_rejects_a_bad_value(bad):
    with pytest.raises(ValidationError):
        i18n.CountryPack(code="zz", name="Zz", cv=bad)


def test_cv_conventions_follow_the_location_s_country_and_default_to_neutral():
    assert i18n.cv_conventions_for_location("Copenhagen").photo == "optional"
    assert i18n.cv_conventions_for_location("London, United Kingdom").photo == "no"
    neutral = i18n.cv_conventions_for_location("Atlantis")
    assert (neutral.photo, neutral.date_of_birth, neutral.max_pages) == ("no", False, 2)
    assert i18n.cv_conventions_for_location(None).photo == "no"


def test_preload_loads_the_language_libraries_with_one_blas_thread(monkeypatch):
    # #18: numpy's OpenBLAS hung as it loaded on a worker thread of the Windows server; it is loaded once, up front
    import sys

    monkeypatch.delenv("OPENBLAS_NUM_THREADS", raising=False)
    i18n.preload_language_detection()
    assert os.environ["OPENBLAS_NUM_THREADS"] == "1"
    assert "numpy" in sys.modules and "py3langid.langid" in sys.modules


def test_preload_keeps_a_blas_thread_count_the_user_set(monkeypatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "4")
    i18n.preload_language_detection()
    assert os.environ["OPENBLAS_NUM_THREADS"] == "4"
