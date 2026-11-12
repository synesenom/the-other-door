"""Which postings are local to the profile: by the place names in a job's URL path, and by the location
facets of a Workday job list. Pure; the place names come from src/door/i18n."""

import pytest

from door.matching import locality

DK = {"location": "Copenhagen, Denmark"}


def test_filtering_needs_a_country_the_i18n_data_knows():
    assert locality.enabled(DK)
    assert locality.enabled({"location": "Aarhus"})
    assert not locality.enabled({"location": "Atlantis"})
    assert not locality.enabled({})


@pytest.mark.parametrize("path, non_local", [
    ("/job/Chicago-Illinois/Data-Scientist_R1", True),
    ("/job/Bangalore/Engineer_R2", True),
    ("/job/Munich-Germany/Engineer_R2", True),
    ("/job/Copenhagen/Data-Scientist_R3", False),
    ("/job/Ballerup-Denmark/Engineer_R4", False),
    ("/job/Aarhus/Engineer_R5", False),
    ("/job/Remote-Germany/Engineer_R6", False),          # remote jobs stay
    ("/job/Copenhagen-and-London/Engineer_R7", False),    # names a local place too
    ("/job/Engineer-Platform_R8", False),                 # no place at all: kept
    ("/job/Hybrid/Engineer_R9", False),
    ("/careers/join-us/reading-list-editor_R10", False),   # "us" and "reading" are words, not places
    ("/en/careers/job/12345/senior-data-scientist-denmark", False),
])
def test_a_path_naming_only_another_places_is_non_local(path, non_local):
    assert locality.path_is_non_local(path, DK) is non_local


def test_nothing_is_non_local_without_a_known_country():
    assert locality.path_is_non_local("/job/Chicago/Engineer_R1", {"location": "Atlantis"}) is False


def test_split_urls_separates_the_non_local_ones():
    urls = ["https://x.com/job/Chicago/A_R1", "https://x.com/job/Copenhagen/B_R2", "https://x.com/job/Munich/C_R3"]
    assert locality.split_urls(urls, DK) == (["https://x.com/job/Copenhagen/B_R2"], 2)
    assert locality.split_urls(urls, {"location": "Atlantis"}) == (urls, 0)


def _facets(*groups):
    """A Workday answer's facets with a `locationMainGroup` holding nested location facets."""
    return [{"facetParameter": "timeType", "descriptor": "Time", "values": [{"descriptor": "Full time", "id": "ft", "count": 3}]},
            {"facetParameter": "locationMainGroup", "values": [
                {"facetParameter": param, "descriptor": param,
                 "values": [{"descriptor": d, "id": i, "count": 1} for d, i in values]}
                for param, values in groups]}]


def test_the_local_values_of_a_location_facet_are_picked():
    facets = _facets(("locations", [("Acton, Massachusetts, US", "a"), ("Copenhagen, Denmark", "c"), ("Aarhus, Denmark", "d"),
                                    ("Remote", "r"), ("Munich, Germany", "m")]))
    assert locality.location_filter(facets, DK) == ("locations", ["c", "d", "r"])


def test_a_country_level_facet_is_preferred_over_the_sites():
    facets = _facets(("locations", [("Denmark, Roskilde", "s1"), ("Denmark, Remote", "s2")]),
                     ("locationHierarchy1", [("Germany", "g"), ("Denmark", "dk")]))
    assert locality.location_filter(facets, DK) == ("locationHierarchy1", ["dk"])


def test_a_flat_location_country_facet_works_too():
    facets = [{"facetParameter": "locationCountry", "descriptor": "Country",
               "values": [{"descriptor": "Denmark", "id": "dk", "count": 4}, {"descriptor": "France", "id": "fr", "count": 9}]}]
    assert locality.location_filter(facets, DK) == ("locationCountry", ["dk"])


def test_a_tenant_with_no_local_location_has_nothing_local():
    facets = _facets(("locations", [("Armenia", "a"), ("Remote", "r"), ("Austin, Texas, US", "t")]))
    assert locality.location_filter(facets, DK) == ("locations", [])


def test_no_location_facet_or_no_known_country_means_no_filter():
    assert locality.location_filter([{"facetParameter": "timeType", "values": []}], DK) is None
    assert locality.location_filter(None, DK) is None
    assert locality.location_filter(_facets(("locations", [("Copenhagen, Denmark", "c")])), {"location": "Atlantis"}) is None


def test_country_code_of_the_profile_and_a_posting_in_another_country():
    assert locality.country_code(DK) == "dk" and locality.country_code({"location": "Atlantis"}) is None
    assert locality.country_is_non_local("se", DK) is True
    assert locality.country_is_non_local("DK", DK) is False
    assert locality.country_is_non_local("se", DK, remote=True) is False   # remote work stays
    assert locality.country_is_non_local(None, DK) is False                # no location info stays
    assert locality.country_is_non_local("se", {"location": "Atlantis"}) is False


HU = {"location": "Budapest, Hungary"}


def test_hungary_is_known_and_its_cities_are_local():
    assert locality.enabled(HU)
    assert locality.country_code(HU) == "hu"
    names = [n.lower() for n in locality.local_names(HU)]
    assert "budaörs" in names and "debrecen" in names and "magyarország" in names


@pytest.mark.parametrize("path, non_local", [
    ("/job/Budapest/Data-Scientist_R1", False),
    ("/job/Debrecen/Engineer_R2", False),
    ("/job/Vienna/Engineer_R3", True),
])
def test_hungarian_job_paths(path, non_local):
    assert locality.path_is_non_local(path, HU) is non_local


HU = {"location": "Budapest, Hungary"}


@pytest.mark.parametrize("text", [
    "London, UK", "Bangalore, Karnataka, IN", "Walldorf, Germany", "Boston, MA", "Palo Alto, CA, US", "Aachen, DE",
    "Milan, IT", "Rome, IT", "Zagreb, HR", "Doha, QA", "Puerto Rico, PR", "Mississauga, ON",
])
def test_location_is_non_local_flags_foreign(text):
    assert locality.location_is_non_local(text, HU)


@pytest.mark.parametrize("text", [
    "Budapest", "Budapest, HU", "Budapest, Hungary", "", None, "Remote",
    "London, UK; Budapest, HU", "Hungary", "Remote, IT", "Budapest, IT", "Hybrid", "Support Team",
    "Remote, PR",
])
def test_location_is_non_local_keeps_local_remote_and_empty(text):
    assert not locality.location_is_non_local(text, HU)


def test_location_is_non_local_needs_a_known_country():
    assert not locality.location_is_non_local("London, UK", {"location": "Mars"})
    assert not locality.location_is_non_local("London, UK", {})


def test_split_postings_drops_foreign_and_counts():
    postings = [{"location": "London, UK"}, {"location": "Budapest"}, {"location": ""}, {}]
    kept, dropped = locality.split_postings(postings, HU)
    assert kept == postings[1:] and dropped == 1
    assert locality.split_postings(postings, {"location": "Mars"}) == (postings, 0)


# --- #432: home-based jobs and the whole world's countries -------------------------------------------------

@pytest.mark.parametrize("text", [
    "Home-based", "Home based, Kenya", "Homebased (Kenya)", "Hjemmebaseret, Kenya", "Hjemmefra, Uganda",
    "Home-based with travel to South Sudan",
])
def test_a_home_based_job_is_not_non_local_whatever_country_it_names(text):
    assert not locality.location_is_non_local(text, DK)


def test_a_hungarian_profile_keeps_a_home_based_job_too():
    assert not locality.location_is_non_local("Otthonról, Kenya", HU)


# One name for every country of the world (ISO 3166 short names in English; the Copenhagen profile's own
# Denmark excluded): a posting naming only one of them is not local, whichever cities the data lists.
_COUNTRIES = """Afghanistan, Albania, Algeria, Andorra, Angola, Antigua and Barbuda, Argentina, Armenia, Australia,
Austria, Azerbaijan, Bahamas, Bahrain, Bangladesh, Barbados, Belarus, Belgium, Belize, Benin, Bhutan, Bolivia,
Bosnia and Herzegovina, Botswana, Brazil, Brunei, Bulgaria, Burkina Faso, Burundi, Cabo Verde, Cambodia, Cameroon,
Canada, Central African Republic, Chad, Chile, China, Colombia, Comoros, Congo, DR Congo, Costa Rica, Cote d'Ivoire,
Côte d'Ivoire, Croatia, Cuba, Cyprus, Czechia, Djibouti, Dominica, Dominican Republic, Ecuador, Egypt, El Salvador,
Equatorial Guinea, Eritrea, Estonia, Eswatini, Ethiopia, Fiji, Finland, France, Gabon, Gambia, Georgia, Germany,
Ghana, Greece, Grenada, Guatemala, Guinea, Guinea-Bissau, Guyana, Haiti, Honduras, Hungary, Iceland, India,
Indonesia, Iran, Iraq, Ireland, Israel, Italy, Jamaica, Japan, Jordan, Kazakhstan, Kenya, Kiribati, Kosovo, Kuwait,
Kyrgyzstan, Laos, Latvia, Lebanon, Lesotho, Liberia, Libya, Liechtenstein, Lithuania, Luxembourg, Madagascar,
Malawi, Malaysia, Maldives, Mali, Malta, Marshall Islands, Mauritania, Mauritius, Mexico, Micronesia, Moldova,
Monaco, Mongolia, Montenegro, Morocco, Mozambique, Myanmar, Namibia, Nauru, Nepal, Netherlands, New Zealand,
Nicaragua, Niger, Nigeria, North Korea, North Macedonia, Norway, Oman, Pakistan, Palau, Palestine, Panama,
Papua New Guinea, Paraguay, Peru, Philippines, Poland, Portugal, Qatar, Romania, Russia, Rwanda,
Saint Lucia, Samoa, San Marino, Sao Tome and Principe, Saudi Arabia, Senegal, Serbia, Seychelles, Sierra Leone,
Singapore, Slovakia, Slovenia, Solomon Islands, Somalia, South Africa, South Korea, South Sudan, Spain, Sri Lanka,
Sudan, Suriname, Sweden, Switzerland, Syria, Taiwan, Tajikistan, Tanzania, Thailand, Timor-Leste, Togo, Tonga,
Trinidad and Tobago, Tunisia, Turkey, Turkmenistan, Tuvalu, Uganda, Ukraine, United Arab Emirates, United Kingdom,
United States, Uruguay, Uzbekistan, Vanuatu, Venezuela, Vietnam, Yemen, Zambia, Zimbabwe, Somaliland,
Democratic Republic of the Congo, Occupied Palestinian Territory, Gaza, West Bank, Hong Kong, Puerto Rico"""


@pytest.mark.parametrize("country", [c.strip() for c in _COUNTRIES.replace("\n", " ").split(",") if c.strip()])
def test_every_country_of_the_world_is_foreign_to_a_copenhagen_profile(country):
    assert locality.location_is_non_local(country, DK), country
    assert locality.location_is_non_local(f"Juba, {country}", DK), country


@pytest.mark.parametrize("text", ["Udlandet", "Abroad", "Overseas", "Various locations abroad"])
def test_abroad_words_are_foreign(text):
    assert locality.location_is_non_local(text, DK)


def test_a_hungarian_abroad_word_is_foreign_for_a_budapest_profile():
    assert locality.location_is_non_local("Külföld", HU)


def test_a_bare_unknown_city_is_ambiguous_and_kept():
    assert not locality.location_is_non_local("Juba", DK)
    assert not locality.location_is_non_local("Kyiv", DK)


@pytest.mark.parametrize("name", [
    "Syrian Arab Republic", "Russian Federation", "Türkiye", "Viet Nam", "Lao People's Democratic Republic",
    "Venezuela (Bolivarian Republic of)", "United States of America",
    "United Kingdom of Great Britain and Northern Ireland", "Iran (Islamic Republic of)", "Bolivia (Plurinational State of)",
])
def test_the_un_names_of_countries_are_foreign_too(name):
    assert locality.location_is_non_local(name, DK)


def test_is_remote_reads_remote_hybrid_and_home_based_words():
    assert locality.is_remote("Consultant (home-based)") and locality.is_remote("Remote, EU")
    assert locality.is_remote("Hjemmebaseret stilling") and not locality.is_remote("Nairobi, Kenya")
    assert not locality.is_remote("")


FR = {"location": "Paris, France"}


def test_france_is_known_and_its_cities_are_local():
    assert locality.enabled(FR)
    assert locality.country_code(FR) == "fr"
    names = [n.lower() for n in locality.local_names(FR)]
    assert "lyon" in names and "toulouse" in names and "france" in names and "paris*" in names


@pytest.mark.parametrize("path, non_local", [
    ("/job/Paris/Data-Scientist_R1", False),
    ("/job/Lyon/Engineer_R2", False),
    ("/job/Berlin/Engineer_R3", True),
])
def test_french_job_paths(path, non_local):
    assert locality.path_is_non_local(path, FR) is non_local


@pytest.mark.parametrize("text, non_local", [
    ("Paris", False), ("75 - Paris 8e Arrondissement", False), ("92 - Puteaux", False), ("Paris, FR", False),
    ("Lille, France", False), ("Remote", False), ("Berlin, DE", True), ("London, UK", True), ("Munich, Germany", True),
])
def test_french_locations(text, non_local):
    assert locality.location_is_non_local(text, FR) is non_local


SE = {"location": "Stockholm, Sweden"}


def test_sweden_is_known_and_its_cities_are_local():
    assert locality.enabled(SE)
    assert locality.country_code(SE) == "se"
    names = [n.lower() for n in locality.local_names(SE)]
    assert "solna" in names and "lidingö" in names and "sverige" in names


@pytest.mark.parametrize("path, non_local", [
    ("/job/Stockholm/Data-Scientist_R1", False),
    ("/job/Göteborg/Engineer_R2", False),
    ("/job/Oslo/Engineer_R3", True),
])
def test_swedish_job_paths(path, non_local):
    assert locality.path_is_non_local(path, SE) is non_local


@pytest.mark.parametrize("text", [
    "Stockholm", "Stockholm, SE", "Solna", "Göteborg", "Gothenburg, Sweden", "Malmö", "Sverige", "Remote, Sweden",
    "Stockholm, Sweden; Oslo, NO",
])
def test_swedish_places_are_not_foreign_to_a_stockholm_profile(text):
    assert not locality.location_is_non_local(text, SE)


@pytest.mark.parametrize("text", ["Oslo, Norway", "Helsinki, FI", "Aachen, DE", "Berlin, Germany", "Copenhagen, DK", "Utomlands", "Utlandet"])
def test_other_places_are_foreign_to_a_stockholm_profile(text):
    assert locality.location_is_non_local(text, SE)


GB = {"location": "London, United Kingdom"}


def test_the_united_kingdom_is_known_and_its_cities_are_local():
    assert locality.enabled(GB)
    assert locality.country_code(GB) == "gb"
    names = [n.lower() for n in locality.local_names(GB)]
    assert {"uk", "england", "scotland", "wales", "northern ireland", "manchester", "edinburgh", "glasgow",
            "cambridge", "bristol", "leeds"} <= set(names)
    assert "ireland" not in names and "dublin" not in names


@pytest.mark.parametrize("text, non_local", [
    ("London, UK", False), ("Remote, UK", False), ("Slough, UK", False), ("Belfast, Northern Ireland", False),
    ("London W2 1NY", False), ("Edinburgh, Scotland", False), ("Cardiff, Wales", False), ("Leeds, GB", False),
    ("Dublin, Ireland", True), ("Dublin, IE", True), ("Paris, FR", True), ("Berlin, Germany", True),
    ("Boston, MA", True),
])
def test_british_locations(text, non_local):
    assert locality.location_is_non_local(text, GB) is non_local


@pytest.mark.parametrize("text", ["London, UK", "Manchester, England", "Edinburgh, Scotland", "Cardiff, Wales",
                                  "Belfast, Northern Ireland", "Great Britain"])
def test_british_places_are_foreign_to_a_copenhagen_profile(text):
    assert locality.location_is_non_local(text, {"location": "Copenhagen, Denmark"})


@pytest.mark.parametrize("text", ["England", "Scotland", "Wales", "Northern Ireland", "Britain", "UK"])
def test_british_country_names_are_foreign_places(text):
    from door import i18n
    assert text in i18n.foreign_places()
    assert locality.location_is_non_local(text, {"location": "Budapest, Hungary"})


def test_british_names_resolve_to_the_united_kingdom():
    from door import i18n
    for text in ("UK", "United Kingdom", "England", "London"):
        assert i18n.country_for_location(text).code == "gb"


@pytest.mark.parametrize("path, non_local", [
    ("/job/London/Engineer_R1", False), ("/job/Manchester-United-Kingdom/Engineer_R2", False),
    ("/job/Dublin/Engineer_R3", True),
])
def test_british_job_paths(path, non_local):
    assert locality.path_is_non_local(path, GB) is non_local


# --- #598: a remote job tied to another country is not local ----------------------------------------------

@pytest.mark.parametrize("config, text, non_local", [
    (GB, "Remote, Portugal - Lisbon, Portugal", True),
    (DK, "Remote, Portugal - Lisbon, Portugal", True),
    (HU, "Remote, London, UK", True),
    (GB, "Remote, UK", False),
    (GB, "Remote", False),
    (DK, "Remote, Denmark", False),
    (GB, "Remote - EMEA", False),
    (GB, "Remote, Europe", False),
    (DK, "Home-based, Kenya", False),   # home-based and hybrid words do not pin a country
])
def test_a_remote_job_tied_to_a_foreign_country_is_non_local(config, text, non_local):
    assert locality.location_is_non_local(text, config) is non_local
