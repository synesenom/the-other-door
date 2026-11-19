"""The model's reading of a CV's structure (#343), for tests: no test reaches a model.

`recorded(name)` is an answer recorded for a style corpus case (`tests/style/fixtures/styles/structure/<name>.json`,
ids and kinds only; `scripts/record_structure.py` records them again) and `fake_ask(text)` the stand-in the autouse
fixture of `tests/conftest.py` puts where `style_structure` asks: it reads the same input the model gets and answers by
a plain rule (the name is the largest text of the first page, the headings are the lines of at most six words set
unlike the body that a section kind names, one column, not LinkedIn, the contact lines those that look like an email,
a link, a phone number or a period, the footers the page numbers), so a test that reads any PDF finds the
structure it expects without a model; the corpus CVs get their recorded answers.
"""

import functools
import importlib.util
import json

from paths import TESTS_DIR

RECORDED = TESTS_DIR / "style" / "fixtures" / "styles" / "structure"


@functools.cache
def _world_structure():
    """The app's test world's stand-in, `app/test/world/structure.py`, which the stand-in `claude` runs too."""
    spec = importlib.util.spec_from_file_location("world_structure", TESTS_DIR.parent / "app" / "test" / "world" / "structure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recorded(name: str) -> dict:
    return json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))


@functools.cache
def _corpus() -> tuple[dict[str, dict], set[str]]:
    """The recorded answers by the model input of the PDF they were recorded for, and the inputs of the corpus PDFs
    that have none (a scan has no input to answer)."""
    from door.style import style_extract, style_structure

    answers, unrecorded = {}, set()
    for pdf in sorted(RECORDED.parent.glob("*.pdf")):
        pages = style_extract.read_pages(pdf)
        text = style_structure.rows(pages)[0]
        if (RECORDED / f"{pdf.stem}.json").is_file():
            answers[text] = recorded(pdf.stem)
        elif any(r["text"].strip() for p in pages for r in p["runs"]):
            unrecorded.add(text)
    return answers, unrecorded


def fake_ask(text: str, feature: str = "style") -> dict:
    """The recorded answer when `text` is the input of a corpus CV (one with none fails: record it with
    `scripts/record_structure.py`), else the world's plain rule."""
    answers, unrecorded = _corpus()
    if text in answers:
        return answers[text]
    assert text not in unrecorded, "a corpus CV has no recorded answer: run scripts/record_structure.py"
    return _world_structure().answer(text)


def structure_of(pdf, answer: dict) -> dict:
    """`answer` held to `style_structure.check` over the PDF's own lines."""
    from door.style import style_extract, style_structure

    pages = style_extract.read_pages(pdf)
    return style_structure.check(answer, style_structure.rows(pages)[1], pages)


def extract_with(pdf, answer: dict) -> dict:
    """`style_extract.extract` of the PDF given the structure `answer` makes (a recorded answer, say)."""
    from door.style import style_extract

    return style_extract.extract(pdf, structure=structure_of(pdf, answer))
