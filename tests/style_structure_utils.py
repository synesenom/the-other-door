"""The model's reading of a CV's structure (#343), for tests: no test reaches a model.

`recorded(name)` is an answer recorded for a style corpus case (`tests/tailoring/fixtures/styles/structure/<name>.json`,
ids and kinds only; `scripts/record_structure.py` records them again) and `fake_ask(text)` the stand-in the autouse
fixture of `tests/conftest.py` puts where `style_structure` asks: it reads the same input the model gets and answers by
a plain rule (the name is the largest text of the first page, the headings are the lines of at most six words set
unlike the body that a section kind names, one column, not LinkedIn), so a test that reads any PDF finds the
structure it expects without a model; the corpus CVs get their recorded answers.
"""

import functools
import importlib.util
import json

from paths import TESTS_DIR

RECORDED = TESTS_DIR / "tailoring" / "fixtures" / "styles" / "structure"


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
def _corpus() -> dict[str, dict]:
    """The recorded answers by the model input of the PDF they were recorded for."""
    from door.tailoring import style_extract, style_structure

    pdfs = RECORDED.parent
    return {style_structure.rows(style_extract.read_pages(pdfs / f"{f.stem}.pdf"))[0]: recorded(f.stem)
            for f in sorted(RECORDED.glob("*.json")) if (pdfs / f"{f.stem}.pdf").is_file()}


def fake_ask(text: str, feature: str = "style") -> dict:
    """The recorded answer when `text` is the input of a corpus CV, else the world's plain rule."""
    if text in _corpus():
        return _corpus()[text]
    return _world_structure().answer(text)


def structure_of(pdf, answer: dict) -> dict:
    """`answer` held to `style_structure.check` over the PDF's own lines."""
    from door.tailoring import style_extract, style_structure

    pages = style_extract.read_pages(pdf)
    return style_structure.check(answer, style_structure.rows(pages)[1], pages)


def extract_with(pdf, answer: dict) -> dict:
    """`style_extract.extract` of the PDF given the structure `answer` makes (a recorded answer, say)."""
    from door.tailoring import style_extract

    return style_extract.extract(pdf, structure=structure_of(pdf, answer))
