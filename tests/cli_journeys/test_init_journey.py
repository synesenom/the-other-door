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
FRENCH_PDF = TESTS_DIR / "commands" / "fixtures" / "scrubbed-altacv-icons-fr.pdf"

# persona: (the CV file it hands over, words naming its fresh ad, text its CV file must reach the model with;
# lea's and bence's last item is a word their PDF breaks over two lines with a hyphen, which must come back joined)
CASES = {
    "mette": ("docx", "varmeværk", ["KJÆR", "Vindstrøm", "Øresund", "–", "•"]),
    "lea": ("fixture", "ferrovia", ["émerveillement", "Côté", "A’lequartier", "4707 – 7772", "○", "•",
                                    "Silencieusementfroidimage"]),
    "bence": ("pdf", "pannon", ["Kovács", "Szoftverfejlesztő", "Műhely", "–", "“Idempotent consumers in practice”",
                                "Bartók’s whole œuvre on vinyl"]),
    "asa": ("pdf", "göta älv", ["ÅSA SÖDERLUND", "Göteborg", "Älvstrand", "Västkustens Värmeverk", "–", "•"]),
}


def _docx(path: Path, text: str) -> Path:
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(line)}</w:t></w:r></w:p>" for line in text.split("\n"))
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml.encode("utf-8"))
    return path


def _source(world: World, kind: str, name: str | None = None) -> Path:
    """The persona's CV as the file the user hands over, in the data folder beside the world's Markdown copy:
    a DOCX or a PDF of it, or (`fixture`) the French PDF."""
    text = Path(world.info["cvFile"]).read_text(encoding="utf-8")
    path = Path(world.info["cvFile"]).with_suffix(".docx" if kind == "docx" else ".pdf")
    if name:
        path = path.with_name(name)
    if kind == "docx":
        return _docx(path, text)
    if kind == "pdf":
        lines = text.split("\n")
        return make_pdf(path, ["\n".join(lines[i:i + 50]) for i in range(0, len(lines), 50)], size=10, font=FIGTREE)
    path.write_bytes(FRENCH_PDF.read_bytes())
    return path


def _init_find_show_prepare(world: World, persona: str, cv_name: str | None = None) -> None:
    """init from the persona's CV file, the first run it starts, then `jobs show` and `jobs prepare` of the fresh ad:
    every character of the CV and of the ad kept on the way to the model, the disk and the printed PDFs."""
    kind, words, kept = CASES[persona]
    # once: a source that cannot be read is asked for again, and the second answer (empty) skips the draft
    world.script_prompts({"cv_sources": {"sequence": [str(_source(world, kind, cv_name))]}})
    code, out, err = world.door("init")
    assert code == 0, f"{out}\n{err}"
    assert "No sources" not in out, err   # "Your sources could not be read: 'charmap' codec can't encode ..." (#134)
    assert f"Wrote {Path('profile/config.json')}." in out
    assert "[1/5] search" in out and "[5/5] match" in out, out   # the first run it starts

    drafted = world.claude_inputs("draft")
    assert drafted, world.claude_kinds()
    for text in kept:
        assert text in drafted[0], (text, drafted[0][:2000])
    assert "￾" not in drafted[0] and "\x11" not in drafted[0]

    cv = (world.home / "profile" / "cv.md").read_text(encoding="utf-8")
    assert cv == world.persona["cv"]
    for call in ("basics", "titles"):   # the other reading steps read the draft whole
        assert cv.strip() in world.claude_inputs(call)[0], call
    config = world.read("profile/config.json")
    assert config["name"] == world.persona["name"] and config["location"] == world.persona["city"]
    assert all(title in world.claude_inputs("keywords")[0] for title in config["role_targets"])

    ad = next(a for a in world.jobs.values() if words in (a["title"] + " " + a["company"]).lower())
    posting = next((world.home / "jobs" / "postings").glob(f"*/*/{ad['id']}.json"))
    stored = json.loads(posting.read_text(encoding="utf-8"))
    assert stored["company"] == ad["company"] and stored["title"] in ad["title"]   # a gender mark (H/F) cut off
    boards = json.loads((world.dir / "world.json").read_text(encoding="utf-8"))["boards"]
    sent = next(p for b in boards.values() for p in b["postings"] if p["id"] == ad["id"])
    assert stored["description"] == sent["description"]
    scored = [text for text in world.claude_inputs("score") if stored["title"] in text]
    assert scored and world.persona["name"] in scored[0]
    assert stored.get("score") is not None, stored

    code, out, err = world.door("jobs", "show", words)
    assert code == 0, f"{out}\n{err}"
    assert stored["title"] in out and ad["company"] in out

    code, out, err = world.door("jobs", "prepare", words)
    assert code == 0, f"{out}\n{err}"
    folder = world.home / "jobs" / "output" / ad["id"]
    assert ad["id"] in world.claude_inputs("tailor")[-1]
    handed = json.loads((folder / "posting.json").read_text(encoding="utf-8"))   # the posting the tailor read
    assert (handed["title"], handed["description"]) == (stored["title"], stored["description"])

    code, out, err = world.door("jobs", "show", words)   # the printed PDFs read back: name, headings, keywords, all the text
    assert code == 0, f"{out}\n{err}"
    assert any("Read by an ATS" in line and "text reads cleanly" in line for line in out.splitlines()), out


@pytest.fixture(scope="module")
def world():
    return build_world("mette", empty=True)


def test_init_then_the_first_find(world):
    _init_find_show_prepare(world, "mette")
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
def test_a_cv_in_its_own_language_through_init_the_first_run_and_prepare(persona):
    _init_find_show_prepare(build_world(persona, empty=True), persona)


def test_non_ascii_data_folder_and_cv_name():
    """#277: a data folder and a CV file named with non-ASCII characters (C:\\Users\\Zoé\\..., "Åsa Söderlund CV.pdf")
    reach argv, DOOR_HOME and the cwd of every step: init, find, show and prepare."""
    world = build_world("asa", empty=True, home_name="Zoé Åsa-home")
    assert "Zoé" in str(world.home)
    _init_find_show_prepare(world, "asa", cv_name="Åsa Söderlund CV.pdf")

    # the same characters in argv (`poetry -C` in the launcher moves the cwd to the checkout, so a path, not a cwd)
    ad = world.home / "Älvstrand annons.md"
    ad.write_text("Vi söker en ingenjör i Göteborg.\n", encoding="utf-8")
    code, out, err = world.door("jobs", "add", str(ad), "--title", "Ingenjör", "--company", "Älvstrand AB")
    assert code == 0, f"{out}\n{err}"
    assert "Älvstrand AB" in out, out
