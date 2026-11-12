"""Language and country data for the matching passes.

Everything that depends on the language an ad is written in (section headings,
requirement and seniority words, the phrases that make a language a
requirement) lives in ``lang/<iso-639-1>.toml``; everything that depends on the country (city names
and their aliases, company-form suffixes, currency words) lives in
``country/<iso-3166-1>.toml``; ``common.toml`` holds what applies everywhere.
Each file is validated on load (``extra="forbid"``), so a typo fails loudly.

Countries and languages are separate on purpose: a country can post in several
languages and a worldwide board posts in all of them, so a posting's language
is detected from its description (``detect_language``, with ``py3langid``, which
knows ~100 languages), never inferred from its site.

The languages with a data file are the *supported* ones: a profile's
``languages`` may only name these, and ``scrape`` drops ads detected in any
other language (``src/door/matching/language.py``).

Word lists are matched case-insensitively as whole words; a trailing ``*`` also
matches any word starting with it (``"dansk*"`` matches ``"danskkundskaber"``).
Heading lists are the exception: they are matched as substrings of a heading
line (``src/door/matching/condense.py``).

The matching passes apply a language's headings, markers and seniority words
only to ads written in it, plus English ones to every ad (``scope``); language
names and currency words apply to every ad.

Adding a language or a country is a new data file; see docs/adding-a-site.md.
"""

from __future__ import annotations

import re
import unicodedata
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

I18N_DIR = Path(__file__).resolve().parent
LANG_DIR = I18N_DIR / "lang"
COUNTRY_DIR = I18N_DIR / "country"
COMMON_PATH = I18N_DIR / "common.toml"

# The canonical seniority levels; each language maps its own words onto these. `academic` is every
# academic rank (postdoc, assistant or associate professor, professor): a career ladder of its own, where a
# posting for one rank is a fair match for a profile that names another.
SENIORITY_LEVELS = ("junior", "senior", "lead", "principal", "head", "manager", "academic")

# detect_language's minimum confidence (py3langid's normalised probability).
# Full sentences score ~0.75-1.0; a bare title or a list of skills ~0.05-0.4.
_MIN_CONFIDENCE = 0.5

# py3langid codes folded into the code a data file uses: both written
# standards of Norwegian are "no".
_LANGUAGE_ALIASES = {"nb": "no", "nn": "no"}


# A title tag as a data file writes it: letters split by single slashes or dots ("H/F", "F/H/X", "f.h").
_TITLE_TAG = re.compile(r"[^\W\d_]+(?:[/.][^\W\d_]+)+")


def _check_words(words: list[str]) -> list[str]:
    for word in words:
        if not word.strip():
            raise ValueError("empty word")
        if "*" in word[:-1] or word == "*":
            raise ValueError(f"{word!r}: '*' is only allowed at the end of a word")
    return words


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Headings(_Strict):
    requirement: list[str] = []
    responsibility: list[str] = []
    drop: list[str] = []


class Markers(_Strict):
    requirement: list[str] = []
    remote: list[str] = []
    remote_pinned: list[str] = []  # remote words that, beside a country, tie the job to it
    onsite: list[str] = []
    salary: list[str] = []

    @field_validator("*")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        return _check_words(v)


class LanguageRequirement(_Strict):
    required: list[str] = []
    advantage: list[str] = []


class WorkPermit(_Strict):
    no_sponsorship: list[str] = []
    permit_required: list[str] = []
    sponsorship_offered: list[str] = []

    @field_validator("*")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        return _check_words(v)


class Injection(_Strict):
    instruction: list[str] = []     # lines addressed to a model ("ignore previous instructions")
    score_request: list[str] = []   # lines asking for a score or a verdict ("give this candidate a score")

    @field_validator("*")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        return _check_words(v)


class Careers(_Strict):
    link: list[str] = []
    path: list[str] = []    # stems: a URL path holding one is a job page ("vacanc" = vacancy, vacancies)
    nav: list[str] = []     # link texts of a listing that lead on but are not ads ("all jobs", "next")
    apply: list[str] = []   # link or button texts that start an application ("apply now")

    @field_validator("link", "nav", "apply")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        return _check_words(v)


class CvSections(_Strict):
    """Titles of the CV sections the facts check reads (matched as a whole heading)."""

    skills: list[str] = []
    education: list[str] = []
    certifications: list[str] = []

    @field_validator("*")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        return _check_words(v)


class LanguagePack(_Strict):
    code: str
    name: str
    names: list[str] = []
    false_friends: list[str] = []
    career_site_words: list[str] = []
    transliterate: dict[str, str] = {}
    slug_fold: dict[str, str] = {}
    stop_words: list[str] = []
    skill_stop_words: list[str] = []
    cv_sections: CvSections = CvSections()
    headings: Headings = Headings()
    markers: Markers = Markers()
    seniority: dict[str, list[str]] = {}
    language_requirement: LanguageRequirement = LanguageRequirement()
    work_permit: WorkPermit = WorkPermit()
    injection: Injection = Injection()
    careers: Careers = Careers()
    compounds: StrictBool = False         # the language writes compounds as one word (Danish "intensivsygeplejerske")
    plural_suffixes: list[str] = []       # endings a plural or inflected form adds to a word ("er", "e", "r")
    role_nouns: list[str] = []            # generic words of a job title that name no field ("consultant", "partner")
    months: dict[str, int] = {}           # month names and abbreviations (lower case) -> 1..12, all twelve or none
    title_tags: list[str] = []            # gender tags a job title carries ("H/F", "m/k"), dropped from stored titles

    @field_validator("names", "false_friends", "stop_words", "skill_stop_words", "career_site_words", "role_nouns")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        return _check_words(v)

    @field_validator("title_tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        for tag in v:
            if not _TITLE_TAG.fullmatch(tag):
                raise ValueError(f"{tag!r}: a title tag is letters split by '/' or '.' (\"H/F\", \"m/k\")")
        return v

    @field_validator("plural_suffixes")
    @classmethod
    def _suffixes(cls, v: list[str]) -> list[str]:
        for suffix in v:
            if not suffix.strip() or "*" in suffix:
                raise ValueError(f"{suffix!r}: a plural suffix is plain letters")
        return [s.lower() for s in v]

    @field_validator("months")
    @classmethod
    def _months(cls, v: dict[str, int]) -> dict[str, int]:
        for name, number in v.items():
            if not name.strip() or "*" in name:
                raise ValueError(f"{name!r}: a month name is plain text")
            if not 1 <= number <= 12:
                raise ValueError(f"{name!r}: month {number} is not 1..12")
        if v and set(v.values()) != set(range(1, 13)):
            raise ValueError("months must name each of the twelve months")
        return {name.lower(): number for name, number in v.items()}

    @field_validator("seniority")
    @classmethod
    def _levels(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for level, words in v.items():
            if level not in SENIORITY_LEVELS:
                raise ValueError(f"unknown seniority level {level!r}; use one of {SENIORITY_LEVELS}")
            _check_words(words)
        return v


class CvConventions(_Strict):
    """How a CV is written in a country (#605): what the tailor is told and `prepare` obeys.
    ``photo``: "no" (leave it off), "optional" (only if the candidate gave one), "expected";
    ``date_of_birth``: whether the CV conventionally has one (only ever kept when ``cv.md``
    already has it, never added); ``max_pages``; ``date_format``: the country's all-numeric full
    date (``DD``, ``MM``, ``YYYY`` and the separators around them). The default is the neutral one."""

    photo: Literal["no", "optional", "expected"] = "no"
    date_of_birth: StrictBool = False
    max_pages: int = Field(default=2, ge=1, le=3)
    date_format: str = "DD/MM/YYYY"

    @field_validator("date_format")
    @classmethod
    def _date_format(cls, v: str) -> str:
        if [v.count(t) for t in ("DD", "MM", "YYYY")] != [1, 1, 1] or re.search(r"[A-Za-z]", v.replace("DD", "").replace("MM", "").replace("YYYY", "")):
            raise ValueError("date_format must have DD, MM and YYYY once each, with only separators between")
        return v


class CountryPack(_Strict):
    code: str
    name: str
    names: list[str] = []
    languages: list[str] = []
    currency: list[str] = []
    legal_suffixes: list[str] = []
    subsidiary_words: list[str] = []  # a subsidiary's name ends with them, no part of the employer's ("svenska")
    cities: dict[str, list[str]] = {}
    commute: dict[str, list[str]] = {}  # city -> towns within about an hour's commute (same word syntax as cities)
    tlds: list[str] = []          # the country's domain endings ("hu"; "uk" for gb), the first is the host guesses'
    career_hosts: list[str] = []  # host labels its employers put a career site under ("karrier.acme.hu")
    job_boards: list[str] = []    # whole domains of its job boards and recruiters (the domain or a subdomain)
    cv: CvConventions = CvConventions()  # how a CV is written there (photo, date of birth, pages, date format)

    @field_validator("names", "currency", "legal_suffixes", "subsidiary_words")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        return _check_words(v)

    @field_validator("tlds", "career_hosts", "job_boards")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return [w.lower() for w in _check_words(v)]

    @field_validator("cities", "commute")
    @classmethod
    def _aliases(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for aliases in v.values():
            _check_words(aliases)
        return v

    @model_validator(mode="after")
    def _commute_keys_are_cities(self):
        unknown = set(self.commute) - set(self.cities)
        if unknown:
            raise ValueError(f"[commute] names {sorted(unknown)}, not in [cities]")
        return self


class CommonPack(_Strict):
    legal_suffixes: list[str] = []
    subsidiary_words: list[str] = []  # a subsidiary's name ends with them, no part of the employer's ("gbc")
    generic_host_labels: list[str] = []  # host labels that name no employer ("www", "careers", "apply")
    tlds: list[str] = []            # domain endings every country shares ("com", "net", "eu")
    slug_suffixes: list[str] = []   # more words around a name that no URL slug carries (not used to compare names)
    job_id_params: list[str] = []   # query parameters (lower case) that carry a job's id in an ad link
    synonyms: list[list[str]] = []  # groups of terms that mean the same in a job title
    foreign_places: list[str] = []  # countries and cities worldwide: a job that names only these is not local
    slug_transliterate: dict[str, str] = {}  # letters of languages without a file (German ä ö ü ß) a slug spells out
    demo_title_marks: list[str] = []     # in a job title: a platform's demo account ("(sample)")
    demo_title_prefixes: list[str] = []  # at a job title's start: a demo account ("copy of ")
    demo_text_marks: list[str] = []      # in a job's text: placeholder text ("lorem ipsum")

    @field_validator("foreign_places")
    @classmethod
    def _places(cls, v: list[str]) -> list[str]:
        return _check_words(v)

    @field_validator("synonyms")
    @classmethod
    def _groups(cls, v: list[list[str]]) -> list[list[str]]:
        return [[w.lower() for w in _check_words(group)] for group in v]

    @field_validator("generic_host_labels", "tlds")
    @classmethod
    def _labels(cls, v: list[str]) -> list[str]:
        return [w.lower() for w in _check_words(v)]

    @field_validator("demo_title_marks", "demo_title_prefixes", "demo_text_marks")
    @classmethod
    def _demo(cls, v: list[str]) -> list[str]:
        return [w.lower() for w in _check_words(v)]

    @field_validator("job_id_params")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return [w.lower() for w in _check_words(v)]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _read(path: Path) -> dict:
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def load_language_file(path: Path) -> LanguagePack:
    return LanguagePack.model_validate(_read(path))


def load_country_file(path: Path) -> CountryPack:
    return CountryPack.model_validate(_read(path))


def _check_conflicts(packs: dict[str, LanguagePack]) -> None:
    """Fail when two language files disagree on what is shared by every
    language: a letter's ASCII spelling (one transliteration table) or a
    seniority word's level (one word -> level map). Otherwise the first file
    by code would silently win."""
    letters: dict[str, tuple[str, str]] = {}
    levels: dict[str, tuple[str, str]] = {}
    for code, pack in packs.items():
        for letter, ascii_ in pack.transliterate.items():
            seen = letters.setdefault(letter.lower(), (ascii_.lower(), code))
            if seen[0] != ascii_.lower():
                raise ValueError(
                    f"{code}.toml spells {letter!r} as {ascii_!r}, {seen[1]}.toml as {seen[0]!r}"
                )
        for level, words in pack.seniority.items():
            for word in words:
                seen = levels.setdefault(word.lower(), (level, code))
                if seen[0] != level:
                    raise ValueError(
                        f"seniority word {word!r} is {level!r} in {code}.toml but {seen[0]!r} in {seen[1]}.toml"
                    )


@lru_cache(maxsize=1)
def languages() -> dict[str, LanguagePack]:
    """Every language pack, keyed by code, in code order."""
    packs = {p.stem: load_language_file(p) for p in sorted(LANG_DIR.glob("*.toml"))}
    _check_conflicts(packs)
    return packs


@lru_cache(maxsize=1)
def countries() -> dict[str, CountryPack]:
    """Every country pack, keyed by code, in code order."""
    return {p.stem: load_country_file(p) for p in sorted(COUNTRY_DIR.glob("*.toml"))}


@lru_cache(maxsize=1)
def common() -> CommonPack:
    return CommonPack.model_validate(_read(COMMON_PATH))


# --------------------------------------------------------------------------- #
# Matching words
# --------------------------------------------------------------------------- #


def word_pattern(words: list[str]) -> str:
    """A regex alternation matching any of ``words`` as a whole word (a
    trailing ``*`` also matches longer words). Lookarounds instead of ``\\b``,
    so words that start or end in punctuation (``"kr."``) match too."""
    parts = []
    for word in sorted(set(words), key=len, reverse=True):
        if word.endswith("*"):
            parts.append(re.escape(word[:-1]) + r"\w*")
        else:
            parts.append(re.escape(word))
    if not parts:
        return r"(?!x)x"
    return r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)"


def compile_words(words: list[str]) -> re.Pattern:
    return re.compile(word_pattern([w.lower() for w in words]), re.IGNORECASE)


def _union(lists) -> list[str]:
    seen: dict[str, None] = {}
    for words in lists:
        for word in words:
            seen.setdefault(word.lower(), None)
    return list(seen)


def scope(code: str | None) -> tuple[str, ...] | None:
    """The languages whose words apply to an ad written in ``code``: its own
    plus English, which turns up in ads in every language; ``None`` (every
    language) when the language is unknown or has no file. Keeps one
    language's ordinary words (Danish *chef*, "boss") from being read as
    markers in another's ads (English *chef*, a cook)."""
    if not code or code not in languages():
        return None
    return tuple(sorted({code, "en"} & set(languages())))


def _packs(codes: tuple[str, ...] | None) -> list[LanguagePack]:
    """The packs of ``codes`` (``None``: every language)."""
    return [p for c, p in languages().items() if codes is None or c in codes]


def heading_words(kind: str, codes: tuple[str, ...] | None = None) -> list[str]:
    """Heading vocabulary of ``kind`` (requirement / responsibility / drop),
    over the languages ``codes`` (``None``: every language; see ``scope``)."""
    return _union(getattr(p.headings, kind) for p in _packs(codes))


def marker_words(kind: str, codes: tuple[str, ...] | None = None) -> list[str]:
    """Marker words of ``kind`` (requirement / remote / onsite / salary), over
    the languages ``codes`` (``None``: every language; see ``scope``)."""
    return _union(getattr(p.markers, kind) for p in _packs(codes))


def career_words(codes: tuple[str, ...] | None = None) -> list[str]:
    """Words and phrases that make a link a careers page ("careers", "karriere",
    "ledige stillinger"), over the languages ``codes`` (``None``: every language)."""
    return _union(p.careers.link for p in _packs(codes))


def career_path_stems(codes: tuple[str, ...] | None = None) -> list[str]:
    """Stems that make a URL path a job page ("job", "role", "vacanc", "stilling"), matched as
    substrings, over the languages ``codes`` (``None``: every language)."""
    return _union(p.careers.path for p in _packs(codes))


def career_nav_words(codes: tuple[str, ...] | None = None) -> list[str]:
    """Link texts of a job listing that lead on but are not ads ("all jobs", "next"), whole text."""
    return _union(p.careers.nav for p in _packs(codes))


def career_apply_words(codes: tuple[str, ...] | None = None) -> list[str]:
    """Link or button texts that start an application ("apply", "apply now", "ansøg"), whole text,
    over the languages ``codes`` (``None``: every language)."""
    return _union(p.careers.apply for p in _packs(codes))


def job_id_params() -> list[str]:
    """Query parameters (lower case) that carry a job's id in an ad link (``career_job_req_id``)."""
    return list(common().job_id_params)


def language_names() -> list[str]:
    """Words that name a language (``"danish"``, ``"dansk*"``), over every language."""
    return _union(p.names for p in languages().values())


def seniority_words(codes: tuple[str, ...] | None = None) -> dict[str, str]:
    """``{word: canonical level}`` over the languages ``codes`` (``None``:
    every language; see ``scope``)."""
    mapping: dict[str, str] = {}
    for pack in _packs(codes):
        for level, words in pack.seniority.items():
            for word in words:
                mapping.setdefault(word.lower(), level)
    return mapping



def career_site_words() -> list[str]:
    """Generic words a careers site puts around its employer's name
    ("Careers", "Karriere", "Ledige stillinger"), over every language."""
    return _union(p.career_site_words for p in languages().values())


def title_tags() -> list[str]:
    """The gender tags a job title carries ("H/F", "F/H/X", "m/k"), over every language: a title's
    language is not known when it is stored, and a tag means nothing else in another."""
    return _union(p.title_tags for p in languages().values())


# What may stand between a title and a tag that follows it ("Comptable - H/F"), and around what is left.
_TAG_LEAD = r"(?:\s*[-\u2013\u2014|,:])?\s*"
_TITLE_TRIM = " \t-\u2013\u2014|,:"


@lru_cache(maxsize=1)
def _title_tag_pattern() -> re.Pattern | None:
    tags = sorted({t.lower() for t in title_tags()}, key=len, reverse=True)
    if not tags:
        return None
    bodies = "|".join("".join(r"\s*" + re.escape(part) + r"\s*" if part in "/." else re.escape(part)
                              for part in re.split(r"([/.])", tag)) for tag in tags)
    body = f"(?:{bodies})"
    return re.compile(_TAG_LEAD + rf"(?:\(\s*{body}\s*\)|\[\s*{body}\s*\]|(?<![\w/.]){body}(?![\w/]))",
                      re.IGNORECASE)


def strip_title_tags(title: str) -> str:
    """*title* without its gender tags (`title_tags`): bare, in parentheses or brackets, before or
    after the title or between its parts, with the dash or comma that set it off ("Comptable (h/f) -
    Paris" -> "Comptable - Paris"). A tag inside a word or a longer tag ("M/F/D" when only "M/F" is
    listed) stays, and a title that is nothing but a tag is returned as it is."""
    pattern = _title_tag_pattern()
    if pattern is None or not title:
        return title
    out, n = pattern.subn(" ", title)
    if not n:
        return title
    out = re.sub(r"\s+", " ", out).strip(_TITLE_TRIM)
    return out or title


def supported_language_names() -> str:
    """``"English, Danish"``: the supported languages' names, English first."""
    codes = sorted(languages(), key=lambda c: (c != "en", c))
    return ", ".join(languages()[c].name for c in codes)


def language_code(value: str) -> str | None:
    """The code of the supported language ``value`` names (``"English"``,
    ``"danish"``, ``"da"``, any case), or ``None`` when it names none. The
    supported languages are the ones with a data file."""
    wanted = (value or "").strip().lower()
    for code, pack in languages().items():
        if wanted in (code, pack.name.lower()):
            return code
    return None


def language_label(code: str | None) -> str:
    """``"Danish (da)"`` for a known code, the bare code for one without a
    data file, ``"unknown"`` for ``None``."""
    if not code:
        return "unknown"
    pack = languages().get(code)
    return f"{pack.name} ({code})" if pack else code


def false_friends(code: str | None) -> list[str]:
    """English words that are ordinary, unrelated words in language ``code``
    (Danish *intern* means "internal"): an exclude keyword equal to one is not
    applied to an ad written in that language."""
    pack = languages().get(code or "")
    return [w.lower() for w in pack.false_friends] if pack else []


def transliteration() -> dict[int, str]:
    """A ``str.translate`` table spelling out each language's special letters
    in ASCII (Danish ``ø`` -> ``oe``), lower-case, over every language. Applied
    before NFD normalisation, which would otherwise just drop the letter's
    diacritic (``ø`` -> ``o``)."""
    table: dict[str, str] = {}
    for pack in languages().values():
        for letter, ascii_ in pack.transliterate.items():
            table.setdefault(letter, ascii_.lower())
            table.setdefault(letter.upper(), ascii_.lower())
    return str.maketrans(table)


def synonyms() -> list[list[str]]:
    """Groups of terms (lower case) that mean the same in a job title: ``["ai", "artificial intelligence"]``."""
    return common().synonyms


def foreign_places() -> list[str]:
    """Country and city names worldwide (`common.toml`), to tell a job elsewhere from a local one."""
    return common().foreign_places


def stop_words(codes: tuple[str, ...] | None = None) -> list[str]:
    """Filler words (articles, prepositions, conjunctions) that carry no topic,
    over the languages ``codes`` (``None``: every language; see ``scope``)."""
    return _union(p.stop_words for p in _packs(codes))


def role_nouns(codes: tuple[str, ...] | None = None) -> list[str]:
    """Generic words of a job title that name no field ("consultant", "partner", "total"), left out
    of the content words of a keyword the way seniority words are, over ``codes`` (``None``: every language)."""
    return _union(p.role_nouns for p in _packs(codes))


def plural_suffixes(codes: tuple[str, ...] | None = None) -> list[str]:
    """The endings a plural or inflected form adds to a word (English ``s``, Danish ``er``), over ``codes``."""
    return _union(p.plural_suffixes for p in _packs(codes))


def compounding_codes() -> set[str]:
    """The languages that write compounds as one word (``compounds = true`` in their file)."""
    return {code for code, pack in languages().items() if pack.compounds}


def language_codes(names) -> tuple[str, ...]:
    """The codes of the supported languages *names* (a profile's ``languages``) name, in order, unknown
    ones dropped; English when none is left."""
    codes = [c for c in (language_code(str(n)) for n in names or []) if c]
    return tuple(dict.fromkeys(codes)) or ("en",)


def month_numbers(codes: tuple[str, ...] | None = None) -> dict[str, int]:
    """``{month name or abbreviation (lower case): 1..12}`` over the languages ``codes`` (``None``: every
    language), for reading a date written out ("25 octobre 2026")."""
    mapping: dict[str, int] = {}
    for pack in _packs(codes):
        for name, number in pack.months.items():
            mapping.setdefault(name, number)
    return mapping


def skill_stop_words(codes: tuple[str, ...] | None = None) -> list[str]:
    """Generic words (soft skills, months, weekdays) the facts check never claims as a
    skill or tool, over the languages ``codes`` (``None``: every language)."""
    return _union(p.skill_stop_words for p in _packs(codes))


def cv_section(kind: str, codes: tuple[str, ...] | None = None) -> list[str]:
    """Titles of the CV section ``kind`` (skills / education / certifications)."""
    if kind not in CvSections.model_fields:
        raise ValueError(f"unknown CV section {kind!r}; use one of {tuple(CvSections.model_fields)}")
    return _union(getattr(p.cv_sections, kind) for p in _packs(codes))


def _ascii_only(text: str) -> str:
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode()


def slug_spellings(name: str) -> list[str]:
    """The lower-case ASCII spellings a URL slug gives *name*: its special letters spelled out
    (``Hørsholm`` -> ``hoersholm``, the language files' ``transliterate`` and `common.toml`'s
    ``slug_transliterate``), then reduced to their look-alike (``horsholm``, ``slug_fold``). Accents
    fold to their base letter in both."""
    text = (name or "").lower()
    translit = {ord(k): v for k, v in common().slug_transliterate.items()}
    translit |= {ord(k): v for p in languages().values() for k, v in p.transliterate.items()}
    fold = {ord(k): v for p in languages().values() for k, v in p.slug_fold.items()}
    forms = [_ascii_only(text.translate(translit)), _ascii_only(text.translate(fold))]
    return list(dict.fromkeys(f for f in forms if f))


def slug_forms(name: str) -> list[str]:
    """`slug_spellings` plus, last, the form with each special letter dropped (``Hørsholm`` -> ``hrsholm``)."""
    return list(dict.fromkeys([*slug_spellings(name), *([f] if (f := _ascii_only((name or "").lower())) else [])]))


def requirement_phrases() -> dict[str, LanguageRequirement]:
    """``{language name: phrases}`` that make that language a requirement or an advantage."""
    return {
        p.name: p.language_requirement
        for p in languages().values()
        if p.language_requirement.required or p.language_requirement.advantage
    }


def work_permit_phrases() -> dict[str, WorkPermit]:
    """``{language name: phrases}`` about a visa or work permit, for the languages that list any."""
    return {
        p.name: p.work_permit
        for p in languages().values()
        if p.work_permit.no_sponsorship or p.work_permit.permit_required or p.work_permit.sponsorship_offered
    }


def work_permit_words(codes: tuple[str, ...] | None = None) -> list[str]:
    """Every work-permit phrase (all three kinds), lowercased and de-duplicated, over ``codes``."""
    return _union(
        words
        for p in _packs(codes)
        for words in (p.work_permit.no_sponsorship, p.work_permit.permit_required, p.work_permit.sponsorship_offered)
    )


def injection_phrases() -> dict[str, list[str]]:
    """``{"instruction": [...], "score_request": [...]}``: every language's phrases, lowercased."""
    return {
        kind: _union(getattr(p.injection, kind) for p in _packs(None))
        for kind in ("instruction", "score_request")
    }


def currency_words() -> list[str]:
    return _union(c.currency for c in countries().values())


def legal_suffixes() -> list[str]:
    return _union([common().legal_suffixes, *(c.legal_suffixes for c in countries().values())])


def subsidiary_words() -> list[str]:
    """Words a subsidiary's or branch's name ends with that are no part of its employer's own name ("GBC",
    "Svenska", "i Sverige"): `common.toml`'s and every country's, and every country's names."""
    names = (n for c in countries().values() for n in (c.name, *c.names))
    return _union([common().subsidiary_words, *(c.subsidiary_words for c in countries().values()), list(names)])


def slug_suffixes() -> list[str]:
    """Words around an employer's name that are no part of its URL slug: the legal forms of every
    country and the international ones in `common.toml`."""
    return _union([common().slug_suffixes, legal_suffixes()])


def generic_host_labels() -> list[str]:
    """Host labels that name no employer: the fixed ones in `common.toml`, every language's one-word career
    words (also ASCII-folded) and every country's ``career_hosts``. One word each."""
    words = [*common().generic_host_labels,
             *(w for p in languages().values() for w in (*p.careers.link, *p.career_site_words)),
             *(h for c in countries().values() for h in c.career_hosts)]
    forms = (form for w in words if w.strip() and " " not in w.strip() and "*" not in w
             for form in (w.strip().lower(), *slug_spellings(w)))
    return list(dict.fromkeys(forms))


def tld_labels() -> list[str]:
    """Domain endings: every country's ``tlds`` and the global ones in `common.toml`."""
    return _union([*(c.tlds for c in countries().values()), common().tlds])


def job_board_domains() -> list[str]:
    """Whole domains of the countries' job boards and recruiters."""
    return _union(c.job_boards for c in countries().values())


def city_names(location: str) -> list[str]:
    """Every name (canonical + aliases) of each known city that ``location``
    names, over every country; ``[]`` when the city is unknown."""
    names: list[list[str]] = []
    for country in countries().values():
        for canonical, aliases in country.cities.items():
            group = [canonical, *aliases]
            if compile_words(group).search(location or ""):
                names.append(group)
    return _union(names)


def commute_names(location: str) -> list[str]:
    """The towns within about an hour's commute of each known city that
    ``location`` names (the country files' ``[commute]``); ``[]`` when none."""
    names: list[list[str]] = []
    for country in countries().values():
        for canonical, towns in country.commute.items():
            if compile_words([canonical, *country.cities[canonical]]).search(location or ""):
                names.append(towns)
    return _union(names)


def place_names() -> list[str]:
    """Every place name The other door knows: the cities and their aliases, the commute
    towns and country names of every country file, and the countries and cities worldwide of
    `common.toml`. A location naming none of them is a workplace or a building."""
    return _union([
        *([c, *a] for p in countries().values() for c, a in p.cities.items()),
        *(t for p in countries().values() for t in p.commute.values()),
        *([p.name, *p.names] for p in countries().values()),
        foreign_places(),
    ])


def country_for_location(location: str) -> CountryPack | None:
    """The country that ``location`` names (``"Denmark"``, ``"Danmark"``) or
    whose known city (or one of its aliases) it names, or ``None`` when it
    names none."""
    for country in countries().values():
        if compile_words([country.name, *country.names]).search(location or ""):
            return country
        for canonical, aliases in country.cities.items():
            if compile_words([canonical, *aliases]).search(location or ""):
                return country
    return None


def cv_conventions_for_location(location: str | None) -> CvConventions:
    """The CV conventions of the country ``location`` names; the neutral default (no photo, no
    date of birth, two pages) when it names none."""
    country = country_for_location(location or "")
    return country.cv if country else CvConventions()


def known_city(location: str) -> str | None:
    """The known city that ``location`` names, by its canonical name or an alias, written as
    ``known_cities`` writes it; ``None`` when it names none (a country alone names none)."""
    for country in countries().values():
        for canonical, aliases in country.cities.items():
            if compile_words([canonical, *aliases]).search(location or ""):
                return canonical.title()
    return None


def known_cities() -> list[tuple[str, str]]:
    """``[(city, country name), ...]``: every canonical city, title-cased, by
    country then city."""
    return [
        (canonical.title(), country.name)
        for country in sorted(countries().values(), key=lambda c: c.name)
        for canonical in country.cities
    ]

# --------------------------------------------------------------------------- #
# Language detection
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"[^\W\d_]")


@lru_cache(maxsize=1)
def _identifier():
    from py3langid.langid import MODEL_FILE, LanguageIdentifier

    return LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)


def detect_language(text: str) -> str | None:
    """The ISO 639-1 code of the language ``text`` is written in, or ``None``
    when ``py3langid`` isn't confident enough (a bare title, a list of
    skills). Any language py3langid knows, with a data file or not."""
    if not _TOKEN_RE.search(text or ""):
        return None
    code, confidence = _identifier().classify(text)
    if confidence < _MIN_CONFIDENCE:
        return None
    return _LANGUAGE_ALIASES.get(code, code)
