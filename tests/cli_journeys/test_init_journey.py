"""`door init` and the first `find` it starts, the real process on a fresh data folder (#33), from a CV in its
own language (#135): Danish as a DOCX, French, Hungarian and Swedish as PDFs set in real fonts, each then
shown and prepared. Run on Windows too, where text once left the process in the code page (cp1252), which has
no room for ő, ○ or pdfium's soft hyphen (#134)."""

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from cli_world import World, build_world
from paths import REPO_ROOT, TESTS_DIR
from pdf_utils import make_pdf

pytestmark = pytest.mark.cli_journeys

FIGTREE = REPO_ROOT / "profile.example" / "fonts" / "Figtree-Regular.ttf"
# A real French CV, its words scrubbed: accents, ’ and –, a word hyphenated at a line end (pdfium's U+FFFE),
# icon glyphs read as control characters (U+0011), ○ and • bullets: the CV that failed on Windows.
FRENCH_PDF = TESTS_DIR / "tailoring" / "fixtures" / "styles" / "scrubbed-altacv-icons-fr.pdf"

# persona: (the CV file it hands over, words naming its fresh ad, text its CV file must reach the model with)
CASES = {
    "mette": ("docx", "varmeværk", ["KJÆR", "Vindstrøm", "Øresund", "–", "•"]),
    "lea": (FRENCH_PDF, "ferrovia", ["émerveillement", "Côté", "A’lequartier", "4707 – 7772", "○", "•"]),
    "bence": ("pdf", "pannon", ["Kovács", "Szoftverfejlesztő", "Műhely", "–"]),
    "asa": ("pdf", "göta älv", ["ÅSA SÖDERLUND", "Göteborg", "Älvstrand", "Västkustens Värmeverk", "–", "•"]),
}


def _docx(path: Path, text: str) -> Path:
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(line)}</w:t></w:r></w:p>" for line in text.split("\n"))
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml.encode("utf-8"))
    return path


def _source(world: World, kind) -> Path:
    """The persona's CV as the file the user hands over, in the data folder beside the world's Markdown copy."""
    text = Path(world.info["cvFile"]).read_text(encoding="utf-8")
    path = Path(world.info["cvFile"]).with_suffix(f".{kind}" if isinstance(kind, str) else ".pdf")
    if kind == "docx":
        return _docx(path, text)
    if kind == "pdf":
        lines = text.split("\n")
        return make_pdf(path, ["\n".join(lines[i:i + 50]) for i in range(0, len(lines), 50)], size=10, font=FIGTREE)
    path.write_bytes(Path(kind).read_bytes())
    return path


def _model_input(world: World, call: str) -> list[str]:
    return [c["input"] for c in world.calls() if c.get("kind") == "claude" and c.get("call") == call]


def _init_find_show_prepare(world: World, persona: str, monkeypatch) -> None:
    """init from the persona's CV file, the first run it starts, then `jobs show` and `jobs prepare` of the fresh ad:
    every character of the CV and of the ad kept on the way to the model, the disk and the printed PDFs."""
    kind, words, kept = CASES[persona]
    # once: a source that cannot be read is asked for again, and the second answer (empty) skips the draft
    world.script_prompts({"cv_sources": {"sequence": [str(_source(world, kind))]}})
    code, out, err = world.door("init")
    assert code == 0, f"{out}\n{err}"
    assert "No sources" not in out, err   # "Your sources could not be read: 'charmap' codec can't encode ..." (#134)
    assert f"Wrote {Path('profile/config.json')}." in out
    assert "[1/5] search" in out and "[5/5] match" in out, out   # the first run it starts

    drafted = _model_input(world, "draft")
    assert drafted, world.claude_kinds()
    for text in kept:
        assert text in drafted[0], (text, drafted[0][:2000])
    assert "￾" not in drafted[0] and "\x11" not in drafted[0]

    cv = (world.home / "profile" / "cv.md").read_text(encoding="utf-8")
    assert cv == world.persona["cv"]
    config = world.read("profile/config.json")
    assert config["name"] == world.persona["name"] and config["location"] == world.persona["city"]

    ad = next(a for a in world.jobs.values() if words in (a["title"] + " " + a["company"]).lower())
    posting = next((world.home / "jobs" / "postings").glob(f"*/*/{ad['id']}.json"))
    stored = json.loads(posting.read_text(encoding="utf-8"))
    assert stored["company"] == ad["company"] and stored["title"] in ad["title"]   # a gender mark (H/F) cut off
    scored = [text for text in _model_input(world, "score") if stored["title"] in text]
    assert scored and world.persona["name"] in scored[0]
    assert stored.get("score") is not None, stored

    code, out, err = world.door("jobs", "show", words)
    assert code == 0, f"{out}\n{err}"
    assert stored["title"] in out and ad["company"] in out

    code, out, err = world.door("jobs", "prepare", words)
    assert code == 0, f"{out}\n{err}"
    folder = world.home / "jobs" / "output" / ad["id"]
    from door.commands import matches
    from door.core import workspace
    from door.tailoring import pdf_render

    assert world.persona["name"] in pdf_render.page_texts(folder / "cv.pdf")[0]
    monkeypatch.setattr(workspace, "PROFILE_DIR", world.home / "profile")
    assert matches._readability(folder) == []


@pytest.fixture(scope="module")
def world():
    return build_world("mette", empty=True)


def test_init_then_the_first_find(world, monkeypatch):
    _init_find_show_prepare(world, "mette", monkeypatch)
    config = world.read("profile/config.json")
    assert config["email"] == world.persona["email"]
    assert world.persona["cv"] != (REPO_ROOT / "profile.example" / "cv.md").read_text(encoding="utf-8")

    kinds = world.claude_kinds()
    positions = [kinds.index(k) for k in ("draft", "basics", "titles", "keywords")]
    assert positions == sorted(positions), kinds
    prompts = [c["name"] for c in world.calls() if c["kind"] == "prompt"]
    assert prompts.index("review") > prompts.index("titles_pick")

    assert list((world.home / "jobs" / "runs").glob("*.json"))


def test_init_by_flags_asks_nothing(world):
    before = len(world.calls())
    code, out, err = world.door("init", "--name", "Mette Test", "--email", "m@example.com", "--set", "min_score=0.5")
    assert code == 0, f"{out}\n{err}"
    assert world.read("profile/config.json")["min_score"] == 0.5
    assert not [c for c in world.calls()[before:] if c["kind"] == "prompt"]


@pytest.mark.parametrize("persona", ["lea", "bence", "asa"])
def test_a_cv_in_its_own_language_through_init_the_first_run_and_prepare(persona, monkeypatch):
    _init_find_show_prepare(build_world(persona, empty=True), persona, monkeypatch)
