"""Unit tests for matching/language.py: tagging each posting's language,
dropping ads outside the profile's `languages`, and batch-translating the kept
non-English titles into ``title_en``. `claude -p` is always faked
(``run_fn``), so these are offline."""

import json
import subprocess

import pytest

from door.matching import language

# The real runner, captured before the autouse fixture in tests/conftest.py
# replaces it with one that never calls `claude`.
from door.matching.language import _run_claude as real_run_claude

_DANISH_DESC = (
    "Vi søger en erfaren dataforsker, som har lyst til at arbejde med machine "
    "learning og Python i vores team."
)
_SWEDISH_DESC = (
    "Vi söker en erfaren data scientist som har erfarenhet av Python och "
    "maskininlärning. Du kommer att arbeta med vårt team på kontoret i Stockholm."
)
_NORWEGIAN_DESC = (
    "Vi søker en erfaren dataforsker som har erfaring med Python og maskinlæring. "
    "Du vil jobbe med teamet vårt på kontoret i Oslo, og det er viktig at du trives."
)
_ENGLISH_DESC = (
    "We are looking for an experienced data scientist who will join our team "
    "and work with machine learning."
)


def _write(tmp_path, job_id, title, description, **extra):
    path = tmp_path / f"{job_id}.json"
    path.write_text(json.dumps({"id": job_id, "title": title, "description": description, **extra}))
    return path


def _read(path):
    return json.loads(path.read_text())


def _envelope(titles: dict) -> str:
    result = {"titles": [{"id": k, "title_en": v} for k, v in titles.items()]}
    return json.dumps({"type": "result", "is_error": False, "result": json.dumps(result)})


# Both supported languages accepted, so Danish ads are kept and translated.
_BOTH = {"languages": ["English", "Danish"]}


def _run(paths, config, run_fn):
    kept, stats = language.filter_languages(paths, config, run_fn=run_fn)
    return kept, stats


class FakeClaude:
    """Translates every title it is sent to "EN <title>"; records each call."""

    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply

    def __call__(self, argv, stdin):
        items = json.loads(stdin)
        self.calls.append((argv, items))
        if self.reply is not None:
            return self.reply
        return _envelope({i["id"]: f"EN {i['title']}" for i in items})


def test_every_posting_is_tagged_with_its_language(tmp_path):
    da = _write(tmp_path, "da-1", "Dataforsker", _DANISH_DESC)
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC)
    unknown = _write(tmp_path, "xx-1", "Data Scientist", "Python, SQL")

    kept, result = _run([da, en, unknown], _BOTH, FakeClaude())
    assert unknown not in kept

    assert _read(da)["language"] == "da"
    assert _read(en)["language"] == "en"
    assert _read(unknown)["language"] is None
    assert result["languages"] == {"da": 1, "en": 1, "unknown": 1}


def test_the_language_is_detected_from_the_description_only(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(language.i18n, "detect_language", lambda text: seen.append(text) or "en")
    _write(tmp_path, "en-1", "Dataforsker", _ENGLISH_DESC)

    _run([tmp_path / "en-1.json"], {}, FakeClaude())

    assert seen == [_ENGLISH_DESC]


def test_an_ad_in_a_language_outside_the_profile_is_dropped(tmp_path):
    """languages: [English] — a Danish ad is cut before condense, prescreen and
    translation, but stays on disk (counted as filtered out by `status`)."""
    da = _write(tmp_path, "da-1", "Dataforsker", _DANISH_DESC)
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC)
    fake = FakeClaude()

    kept, result = _run([da, en], {"languages": ["English"]}, fake)

    assert kept == [en]
    assert _read(da)["score"] == 0.0
    assert _read(da)["score_reason"] == "language: Danish (da) not in languages"
    assert "score" not in _read(en)
    assert fake.calls == []
    assert result["dropped"] == 1


def test_an_unsupported_language_is_dropped_by_its_code(tmp_path):
    no = _write(tmp_path, "no-1", "Data Scientist", _NORWEGIAN_DESC)

    kept, result = _run([no], _BOTH, FakeClaude())

    assert kept == []
    assert _read(no)["score_reason"] == "language: no not in languages"


def test_without_languages_only_english_ads_are_kept(tmp_path):
    da = _write(tmp_path, "da-1", "Dataforsker", _DANISH_DESC)
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC)

    kept, _ = _run([da, en], {}, FakeClaude())

    assert kept == [en]


def test_an_ad_whose_language_is_unclear_is_dropped(tmp_path):
    unknown = _write(tmp_path, "xx-1", "Data Scientist", "Python, SQL")

    kept, result = _run([unknown], {"languages": ["English"]}, FakeClaude())

    assert kept == []
    assert _read(unknown)["score"] == 0.0
    assert _read(unknown)["score_reason"] == "language: unknown not in languages"
    assert result["dropped"] == 1


def test_an_ad_without_a_description_is_dropped(tmp_path):
    """Nothing to score or tailor it against, whatever its language."""
    title_only = _write(tmp_path, "en-1", "Data Scientist", "   \n ")

    kept, result = _run([title_only], {"languages": ["English"]}, FakeClaude())

    assert kept == []
    assert _read(title_only)["score"] == 0.0
    assert _read(title_only)["score_reason"] == "no description"
    assert result["dropped"] == 1


def test_an_unreadable_posting_is_kept(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")

    kept, _ = _run([broken], {"languages": ["English"]}, FakeClaude())

    assert kept == [broken]


def test_only_non_english_titles_are_translated(tmp_path):
    da = _write(tmp_path, "da-1", "Ledende dataforsker", _DANISH_DESC)
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC)
    fake = FakeClaude()

    kept, result = _run([da, en], _BOTH, fake)

    assert _read(da)["title_en"] == "EN Ledende dataforsker"
    assert _read(da)["title"] == "Ledende dataforsker"  # never overwritten
    assert "title_en" not in _read(en)
    assert [i["id"] for i in fake.calls[0][1]] == ["da-1"]
    assert result["translated"] == 1


def test_titles_are_translated_in_batches(tmp_path):
    paths = [_write(tmp_path, f"da-{n}", f"Udvikler {n}", _DANISH_DESC) for n in range(51)]
    fake = FakeClaude()

    kept, result = _run(paths, _BOTH, fake)

    assert [len(items) for _, items in fake.calls] == [language.BATCH_SIZE, 1]
    assert result["translated"] == 51


def test_the_call_uses_haiku_with_no_tools_by_default(tmp_path):
    fake = FakeClaude()
    _run([_write(tmp_path, "da-1", "Udvikler", _DANISH_DESC)], _BOTH, fake)
    argv = fake.calls[0][0]
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--tools") + 1] == ""


def test_translate_model_overrides_the_model(tmp_path):
    fake = FakeClaude()
    _run([_write(tmp_path, "da-1", "Udvikler", _DANISH_DESC)], {**_BOTH, "translate_model": "sonnet"}, fake)
    argv = fake.calls[0][0]
    assert argv[argv.index("--model") + 1] == "sonnet"


@pytest.mark.parametrize("reply", ["not json", _envelope({})])
def test_a_failed_or_empty_translation_leaves_the_posting_untouched(tmp_path, reply):
    da = _write(tmp_path, "da-1", "Udvikler", _DANISH_DESC)

    def run(argv, stdin):
        return reply

    kept, result = _run([da], _BOTH, run)

    assert "title_en" not in _read(da)
    assert _read(da)["language"] == "da"
    assert result["translated"] == 0


def test_a_failed_call_is_counted(tmp_path):
    da = _write(tmp_path, "da-1", "Udvikler", _DANISH_DESC)
    kept, result = _run([da], _BOTH, lambda argv, stdin: None)
    assert result["failed_batches"] == 1


def test_translate_titles_false_makes_no_call(tmp_path):
    da = _write(tmp_path, "da-1", "Udvikler", _DANISH_DESC)
    fake = FakeClaude()

    kept, result = _run([da], {**_BOTH, "translate_titles": False}, fake)

    assert fake.calls == []
    assert _read(da)["language"] == "da"
    assert result["translated"] == 0


def test_an_already_translated_title_is_not_sent_again(tmp_path):
    da = _write(tmp_path, "da-1", "Udvikler", _DANISH_DESC, language="da", title_en="Developer")
    fake = FakeClaude()

    _run([da], _BOTH, fake)

    assert fake.calls == []
    assert _read(da)["title_en"] == "Developer"


def test_an_unknown_id_in_the_reply_is_ignored(tmp_path):
    da = _write(tmp_path, "da-1", "Udvikler", _DANISH_DESC)
    reply = _envelope({"da-1": "Developer", "other": "Something"})

    _run([da], _BOTH, lambda argv, stdin: reply)

    assert _read(da)["title_en"] == "Developer"
    assert not (tmp_path / "other.json").exists()


def test_the_default_runner_reports_a_missing_claude_cli():
    assert real_run_claude(["claude", "-p"], "[]", which=lambda name: None) is None


class _Completed:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_the_default_runner_returns_stdout_on_success():
    seen = {}

    def run(argv, **kwargs):
        seen.update(kwargs)
        return _Completed(0, "OUT")

    out = real_run_claude(["claude", "-p"], "[]", which=lambda name: "/bin/claude", run=run)
    assert out == "OUT"
    assert seen["input"] == "[]"
    assert not any(k.startswith("CLAUDE_CODE_") for k in seen["env"])


def test_the_default_runner_returns_none_on_a_failed_call():
    def run(argv, **kwargs):
        return _Completed(1, "")

    assert real_run_claude(["claude", "-p"], "[]", which=lambda name: "/bin/claude", run=run) is None


def test_the_default_runner_returns_none_when_the_call_cannot_start():
    def run(argv, **kwargs):
        raise OSError("boom")

    assert real_run_claude(["claude", "-p"], "[]", which=lambda name: "/bin/claude", run=run) is None


_HUNGARIAN_DESC = (
    "Tapasztalt adatelemzőt keresünk a budapesti csapatunkba, aki szívesen dolgozik "
    "gépi tanulással és Pythonnal. A munkatársunk a vállalat adataiból készít elemzéseket."
)


def test_a_hungarian_ad_is_kept_when_the_profile_lists_hungarian(tmp_path):
    hu = _write(tmp_path, "hu-1", "Adatelemző", _HUNGARIAN_DESC)

    kept, _ = _run([hu], {"languages": ["English", "Hungarian"]}, FakeClaude())

    assert kept == [hu]
    assert _read(hu)["language"] == "hu"


def test_a_hungarian_ad_is_dropped_when_the_profile_does_not_list_it(tmp_path):
    hu = _write(tmp_path, "hu-1", "Adatelemző", _HUNGARIAN_DESC)

    kept, _ = _run([hu], {"languages": ["English"]}, FakeClaude())

    assert kept == []
    assert _read(hu)["score_reason"] == "language: Hungarian (hu) not in languages"


def test_an_english_ad_from_hungary_is_kept_for_an_english_only_profile(tmp_path):
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC, location="Budapest, Hungary")

    kept, _ = _run([en], {"languages": ["English"], "location": "Budapest, Hungary"}, FakeClaude())

    assert kept == [en]


def test_run_claude_resolves_the_path_and_replaces_argv0(monkeypatch):
    from door.core import installers

    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    monkeypatch.setattr(installers, "find_claude", lambda which=None, home=None: "/x/claude")
    assert real_run_claude(["claude", "-p"], "[]", which=lambda n: None, run=run) == "[]"
    assert seen[0][0] == "/x/claude"


_FRENCH_DESC = (
    "Nous recherchons un analyste de données expérimenté pour rejoindre notre équipe parisienne. "
    "Vous travaillerez sur l’apprentissage automatique avec Python et présenterez vos analyses aux équipes."
)


def test_a_french_ad_is_kept_when_the_profile_lists_french(tmp_path):
    fr = _write(tmp_path, "fr-1", "Analyste de données H/F", _FRENCH_DESC)

    kept, _ = _run([fr], {"languages": ["English", "French"]}, FakeClaude())

    assert kept == [fr]
    assert _read(fr)["language"] == "fr"


def test_a_french_ad_is_dropped_when_the_profile_does_not_list_it(tmp_path):
    fr = _write(tmp_path, "fr-1", "Analyste de données H/F", _FRENCH_DESC)

    kept, _ = _run([fr], {"languages": ["English"]}, FakeClaude())

    assert kept == []
    assert _read(fr)["score_reason"] == "language: French (fr) not in languages"


def test_an_english_ad_from_france_is_kept_for_an_english_only_profile(tmp_path):
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC, location="Paris, France")

    kept, _ = _run([en], {"languages": ["English"], "location": "Paris, France"}, FakeClaude())

    assert kept == [en]


def test_a_swedish_ad_is_kept_when_the_profile_lists_swedish(tmp_path):
    sv = _write(tmp_path, "sv-1", "Dataanalytiker", _SWEDISH_DESC)

    kept, _ = _run([sv], {"languages": ["English", "Swedish"]}, FakeClaude())

    assert kept == [sv]
    assert _read(sv)["language"] == "sv"


def test_a_swedish_ad_is_dropped_when_the_profile_does_not_list_it(tmp_path):
    sv = _write(tmp_path, "sv-1", "Dataanalytiker", _SWEDISH_DESC)

    kept, _ = _run([sv], {"languages": ["English"]}, FakeClaude())

    assert kept == []
    assert _read(sv)["score_reason"] == "language: Swedish (sv) not in languages"


def test_an_english_ad_from_sweden_is_kept_for_an_english_only_profile(tmp_path):
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC, location="Stockholm, Sweden")

    kept, _ = _run([en], {"languages": ["English"], "location": "Stockholm, Sweden"}, FakeClaude())

    assert kept == [en]


def test_an_english_ad_from_the_united_kingdom_is_kept_for_an_english_only_profile(tmp_path):
    en = _write(tmp_path, "en-1", "Data Scientist", _ENGLISH_DESC, location="London, UK")

    kept, _ = _run([en], {"languages": ["English"], "location": "London, United Kingdom"}, FakeClaude())

    assert kept == [en]


# --------------------------------------------------------------------------- #
# tag_posting: an ad the user added on purpose (#73)
# --------------------------------------------------------------------------- #

def test_tag_posting_unreadable_file_returns_empty(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{not json")
    assert language.tag_posting(bad, {}, run_fn=lambda *a: pytest.fail("no call")) == {}


def test_tag_posting_translate_titles_false_makes_no_call(tmp_path):
    path = _write(tmp_path, "a", "Dataforsker", _DANISH_DESC)
    data = language.tag_posting(path, {"translate_titles": False}, run_fn=lambda *a: pytest.fail("no call"))
    assert data["language"] == "da" and "title_en" not in data


def test_tag_posting_too_short_to_detect_is_none(tmp_path):
    path = _write(tmp_path, "a", "Dataforsker", "ok")
    data = language.tag_posting(path, {}, run_fn=lambda *a: pytest.fail("no call"))
    assert data["language"] is None
    assert _read(path)["language"] is None


def test_tag_posting_records_usage_under_the_given_feature(tmp_path, monkeypatch):
    path = _write(tmp_path, "a", "Dataforsker", _DANISH_DESC)
    seen = []
    monkeypatch.setattr(language.usage, "record", lambda feature, *a, **k: seen.append(feature))
    language.tag_posting(path, {}, run_fn=lambda *a: _envelope({"a": "Data scientist"}), feature="import_posting")
    assert seen == ["import_posting"]
