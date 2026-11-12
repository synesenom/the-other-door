from door.matching import title_fit


def test_title_fits_when_it_has_every_word_of_some_keyword_stems_and_order_aside():
    keywords = ["Lead Data Scientist", "Head of AI"]
    assert title_fit.fits("Data Science Lead", keywords)  # "scien…" stems agree
    assert title_fit.fits("Head of AI & Data, Novo Nordisk", keywords)
    assert title_fit.fits("Lead Data Scientist (m/f)", keywords)
    assert not title_fit.fits("Senior Data Scientist", keywords)
    assert not title_fit.fits("Head of Sales", keywords)
    assert not title_fit.fits("Ai Lead", ["Head of AI"])


def test_keywords_prefer_search_keywords_over_role_targets():
    assert title_fit.keywords({"search_keywords": ["a"], "role_targets": ["b"]}) == ["a"]
    assert title_fit.keywords({"search_keywords": [], "role_targets": ["b"]}) == ["b"]
    assert title_fit.keywords({}) == []


# --- on topic: any content word of the keywords (the gate for following and retiring employers) ---------

def test_a_title_is_on_topic_with_any_content_word_of_the_keywords():
    config = {"search_keywords": ["Lead Data Scientist", "Head of AI"]}
    terms = title_fit.topic_terms(config)
    assert title_fit.on_topic("Machine Learning Engineer", ["machine learning"])
    assert title_fit.on_topic("Data Engineer", terms)       # "data" alone is enough
    assert title_fit.on_topic("Scientist, Climate", terms)
    assert not title_fit.on_topic("Head of Sales", terms)    # seniority and stop words are no topic
    assert not title_fit.on_topic("Metadata Librarian", terms)   # whole words only
    assert not title_fit.on_topic("Pedagogue", terms)


def test_topic_words_leave_out_stop_and_seniority_words():
    assert title_fit.topic_words({"role_targets": ["Senior Manager of the Lead", "Data"]}) == ["data"]


def test_synonyms_from_the_i18n_data_count_both_ways():
    ai = title_fit.topic_terms({"role_targets": ["Head of AI"]})
    assert title_fit.on_topic("Technical Lead (Artificial Intelligence)", ai)
    ml = title_fit.topic_terms({"role_targets": ["ML engineer"]})
    assert title_fit.on_topic("Senior Machine Learning Scientist", ml)
    spelled = title_fit.topic_terms({"role_targets": ["Artificial Intelligence lead"]})
    assert title_fit.on_topic("AI Platform Owner", spelled)
    assert not title_fit.on_topic("Intelligence Analyst, Police", ai)  # one word of the phrase is not the phrase


def test_synonyms_cover_professions_outside_tech():
    hr = title_fit.topic_terms({"role_targets": ["HR Business Partner"]})
    assert title_fit.on_topic("Head of Human Resources", hr)
    cfo = title_fit.topic_terms({"role_targets": ["CFO"]})
    assert title_fit.on_topic("Chief Financial Officer", cfo)
    rn = title_fit.topic_terms({"role_targets": ["Registered Nurse"]})
    assert title_fit.on_topic("RN, Night Shift", rn)
    kam = title_fit.topic_terms({"role_targets": ["Key Account Manager"]})
    assert title_fit.on_topic("KAM Nordics", kam)

def test_no_keywords_means_nothing_is_on_topic():
    assert not title_fit.on_topic("Data Scientist", title_fit.topic_terms({}))


# --- the profile's own topic terms (`topic_terms`, proposed with the keywords) ------------------------

def test_with_topic_terms_a_title_needs_one_of_them_or_a_whole_keyword():
    """A shared role noun alone ("analyst") no longer counts: the profile names what does, for any profession."""
    config = {"search_keywords": ["data analyst", "adatelemző"], "topic_terms": ["data", "business intelligence", "bi", "adat*"]}
    terms = title_fit.topic_terms(config)
    assert title_fit.on_topic("Senior Data Analyst", terms)
    assert title_fit.on_topic("BI Analyst", terms)
    assert title_fit.on_topic("Adatelemző", terms)              # a keyword whole
    assert title_fit.on_topic("Adatbázis-fejlesztő", terms)     # a prefix term in a compound
    assert not title_fit.on_topic("Valuation Control Analyst", terms)

    nurse = title_fit.topic_terms({"search_keywords": ["registered nurse"], "topic_terms": ["nurse", "nursing", "sygeplejerske"]})
    assert title_fit.on_topic("Staff Nurse, Night Shift", nurse)
    assert title_fit.on_topic("Registered Nurse", nurse)
    assert not title_fit.on_topic("Registered Accountant", nurse)


def test_without_topic_terms_any_content_word_still_counts():
    assert title_fit.on_topic("Valuation Control Analyst", title_fit.topic_terms({"search_keywords": ["data analyst"]}))
    assert title_fit.on_topic("Valuation Control Analyst", title_fit.topic_terms({"search_keywords": ["data analyst"], "topic_terms": []}))


def test_academic_ranks_are_no_topic_words_but_the_field_stays():
    config = {"search_keywords": ["postdoc physics", "assistant professor physics", "adjunkt fysik", "lektor fysik"]}
    assert title_fit.topic_words(config) == ["fysik", "physics"]


def test_explicit_topic_terms_keep_the_ranks():
    config = {"search_keywords": ["postdoc physics"], "topic_terms": ["postdoc", "physics"]}
    assert title_fit.on_topic("Postdoc, Niels Bohr Institute", title_fit.topic_terms(config))


# --- compounds, plurals, "&" and HTML (#428) ----------------------------------------------------------

def _on(title, *terms):
    return title_fit.on_topic(title, list(terms))


def test_a_leading_star_means_the_term_ends_a_compound():
    assert _on("Intensivsygeplejerske", "*sygeplejerske")
    for title in ["Anæstesisygeplejerske", "Afdelingssygeplejerske", "Hjemmesygeplejerske",
                  "Operationssygeplejerske", "Udviklingssygeplejerske", "Sygeplejerske"]:
        assert _on(title, "*sygeplejerske"), title
    assert not _on("Sygeplejerskeuddannelse", "*sygeplejerske")           # the word must end there
    assert _on("Astrophysics Postdoc", "*physics") and _on("Biophysics postdoc", "*physics")
    assert not _on("Physicist", "*physics")


def test_stars_on_both_sides_match_inside_a_word():
    assert _on("Kræftsygepleje, Rigshospitalet", "*sygepleje*")
    assert _on("Kreditrisikoanalytiker", "*risiko*")
    assert _on("Postdoc i astrofysik", "*fysik*")
    assert not _on("Fysioterapeut", "*fysik*")


def test_a_trailing_star_still_means_a_prefix_only():
    assert _on("Elektrikersvend", "elektriker*")
    assert not _on("Serviceelektriker", "elektriker*")


def test_a_short_whole_word_term_never_matches_inside_a_longer_word():
    assert not _on("Hotel Manager", "el")
    assert _on("El tekniker", "el")


def test_ampersand_and_html_escaped_ampersand_read_as_and():
    assert _on("Monitoring & Evaluation Manager", "monitoring and evaluation")
    assert _on("Monitoring, Evaluation & Learning Advisor", "monitoring and evaluation")
    assert _on("M&amp;E Officer", "m&e")
    assert _on("Senior M&E Advisor", "m&e")
    assert _on("Monitoring and Evaluation Lead", "monitoring & evaluation")


def test_a_hyphenated_compound_is_also_read_joined():
    assert _on("El-installatør", "elinstallatør")
    assert _on("El-installatør", "el installatør")


def test_an_all_caps_term_is_case_sensitive_unless_the_title_is_all_caps():
    assert _on("MEAL Coordinator", "MEAL")
    assert _on("MEAL COORDINATOR", "MEAL")
    assert _on("Senior MEAL/M&E Officer", "MEAL")
    assert not _on("Køkkenmedhjælper til meal prep", "MEAL")
    assert _on("Køkkenmedhjælper til meal prep", "meal")             # lower-case terms stay case-insensitive


def test_squash_and_name_pattern_are_unchanged():
    assert title_fit.squash("Dalsvej-99/Hørsholm") == "dalsvej 99 hrsholm"
    assert title_fit.squash("M&amp;E") == "m amp e"
    assert title_fit.name_pattern(["sygeplejerske"]).search("intensivsygeplejerske") is None


# implicit forms, from the profile's ad languages (`topic_terms`)

_DA = ["English", "Danish"]


def _terms(topic, languages=_DA, keywords=None):
    return title_fit.topic_terms({"search_keywords": keywords or topic[:1], "topic_terms": topic, "languages": languages})


def test_danish_profiles_match_a_field_word_inside_a_compound():
    nurse = _terms(["sygeplejerske", "nurse", "sygepleje"], keywords=["sygeplejerske"])
    for title in ["Intensivsygeplejerske", "Anæstesisygeplejerske", "Afdelingssygeplejerske", "Sygeplejersker til natten",
                  "Kræftsygepleje, Rigshospitalet", "Operationssygeplejerske", "Registered Nurse"]:
        assert title_fit.on_topic(title, nurse), title
    assert not title_fit.on_topic("Fysioterapeut", nurse)
    assert title_fit.on_topic("Serviceelektriker", _terms(["elektriker"]))
    assert title_fit.on_topic("Elektrikersvend", _terms(["elektriker"]))
    assert title_fit.on_topic("Kreditrisikoanalytiker", _terms(["risiko", "risk"]))


def test_every_language_matches_a_long_term_at_the_end_of_a_word_and_plurals():
    english = _terms(["physics", "reward"], languages=["English"])
    assert title_fit.on_topic("Biophysics postdoc", english)
    assert title_fit.on_topic("Postdoc in Astrophysics", english)
    assert title_fit.on_topic("Total Rewards Lead", english)
    assert not title_fit.on_topic("Physicist", english)
    assert title_fit.on_topic("Staff Nurses", _terms(["nurse"], languages=["English"]))


def test_without_a_compounding_language_a_term_is_not_matched_inside_a_word():
    english = _terms(["sygeplejerske"], languages=["English"])
    assert title_fit.on_topic("Intensivsygeplejerske", english)        # ends the word: six letters or more
    assert not title_fit.on_topic("Sygeplejerskeuddannelse", english)  # but does not start a longer one
    assert not title_fit.on_topic("Fysioterapeut", _terms(["fysik"]))  # five letters: whole word only


def test_a_short_topic_term_gets_no_infix_and_no_unrelated_plural():
    terms = _terms(["el", "ai", "data"], keywords=["data"])
    assert not title_fit.on_topic("Hotel Manager", terms)
    assert not title_fit.on_topic("Air Quality Manager", terms)
    assert not title_fit.on_topic("Metadata Librarian", terms)
    assert not title_fit.on_topic("Intelligence Analyst, Police", terms)
    assert title_fit.on_topic("Data Engineer", terms)


def test_a_danish_phrase_gets_the_linking_s_and_a_longer_last_word():
    terms = _terms(["monitorering og evaluering"])
    assert title_fit.on_topic("Monitorerings- og evalueringsrådgiver", terms)
    assert title_fit.on_topic("Rådgiver i monitorering og evaluering", terms)
    assert not title_fit.on_topic("Evalueringsrådgiver", terms)


def test_programmer_is_not_a_program_manager():
    assert not title_fit.on_topic("Programmør", _terms(["program manager"]))
    assert title_fit.on_topic("Program Manager", _terms(["program manager"]))


def test_topic_terms_keeps_the_given_terms_and_stays_a_sorted_list():
    terms = _terms(["sygeplejerske", "adat*", "*fysik*"])
    assert isinstance(terms, list) and terms == sorted(terms)
    assert {"sygeplejerske", "adat*", "*fysik*"} <= set(terms)
    assert title_fit.topic_terms({}) == []


# without topic_terms

def test_role_nouns_are_no_topic_words_but_ampersand_abbreviations_stay():
    words = title_fit.topic_words({"search_keywords": ["reward partner", "C&B specialist", "HR consultant"]})
    assert "partner" not in words and "specialist" not in words and "consultant" not in words
    assert "reward" in words and "c&b" in words and "hr" in words


def test_a_keyword_made_of_role_nouns_only_is_kept_whole():
    assert "consultant" in title_fit.topic_words({"search_keywords": ["consultant"]})
    assert title_fit.topic_words({"role_targets": ["Senior Manager of the Lead"]}) == []


def test_fallback_without_generic_role_nouns():
    terms = title_fit.topic_terms({"search_keywords": ["reward partner", "C&B"]})
    assert title_fit.on_topic("Total Rewards Lead", terms)
    assert title_fit.on_topic("C&B Manager", terms)
    assert not title_fit.on_topic("Partner Manager, Sales", terms)
    assert title_fit.on_topic("Senior M&E Advisor", title_fit.topic_terms({"search_keywords": ["M&E"]}))
    assert title_fit.on_topic("M&amp;E Officer", title_fit.topic_terms({"search_keywords": ["M&E"]}))
    assert not title_fit.on_topic("HR Business Partner", title_fit.topic_terms({"search_keywords": ["monitoring"]}))


def test_fallback_keeps_an_all_caps_keyword_case_sensitive():
    terms = title_fit.topic_terms({"search_keywords": ["MEAL"]})
    assert title_fit.on_topic("MEAL Coordinator", terms)
    assert not title_fit.on_topic("Køkkenmedhjælper til meal prep", terms)


def test_fallback_with_danish_matches_compounds():
    terms = title_fit.topic_terms({"search_keywords": ["elektriker"], "languages": _DA})
    assert title_fit.on_topic("Serviceelektriker", terms) and title_fit.on_topic("Elektrikersvend", terms)
