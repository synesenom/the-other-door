"""Record the model's reading of each style corpus CV (#343): `tests/tailoring/fixtures/styles/structure/<name>.json`,
the answers the offline tests read as if the model had given them (`tests/style_structure_utils.recorded`).

Asks the real model on the local claude's plan (`style_structure._ask`, one call per CV, Haiku) and writes the raw
answer, ids and kinds only, nothing of the CV's text. A name given writes that one; none writes every CV of the
corpus that has a style to copy. Run it after the prompt, the schema or `style_structure.rows` changes (the ids then
mean other lines), then read the diff and run the offline suite:

    poetry run python scripts/record_structure.py [NAME ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from door.tailoring import style_extract, style_structure  # noqa: E402

STYLES = REPO / "tests" / "tailoring" / "fixtures" / "styles"
OUT = STYLES / "structure"


def record(name: str) -> None:
    pages = style_extract.read_pages(STYLES / f"{name}.pdf")
    text, rows = style_structure.rows(pages)
    answer = style_structure._ask(text)
    style_structure.check(answer, rows, pages)  # an answer the checks refuse is not recorded
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(answer, indent=1) + "\n", encoding="utf-8")
    print(f"{name}: recorded")


def main() -> None:
    expected = json.loads((STYLES / "expected.json").read_text(encoding="utf-8"))
    names = sys.argv[1:] or [n for n in sorted(expected) if n != "scan"]
    for name in names:
        try:
            record(name)
        except style_structure.StructureError as exc:
            print(f"{name}: NOT recorded: {exc}")


if __name__ == "__main__":
    main()
