"""What the stand-in `claude` answers the stylist agent (#205): the shipped default template with the fonts the builder
gave (`fonts.css`, in the call's folder) in place of its own, and the example CV as the sample CV, in the fenced
blocks `door.style.style_build.blocks` reads. A call with `default.cover-letter.template.html` beside it is the
letter's, and gets the letter block. Run as `python stylist.py <the call's folder>`; needs `door` importable."""

import re
import sys
from pathlib import Path

from door.core import workspace

folder = Path(sys.argv[1])
example = workspace.PROFILE_EXAMPLE_DIR
letter = (folder / "default.cover-letter.template.html").is_file()
css = (folder / "fonts.css").read_text(encoding="utf-8")
text = (example / ("cover-letter.template.html" if letter else "cv.template.html")).read_text(encoding="utf-8")
text = "\n".join(line for line in text.splitlines() if not line.startswith("@font-face"))
names = re.findall(r'font-family: "([^"]+)"', css)
if names:
    text = text.replace("Figtree, sans-serif", f'"{names[0]}", sans-serif').replace('"Young Serif", serif', f'"{names[-1]}", serif')
text = text.replace("<style>", "<style>\n" + css + "\n", 1)
if letter:
    sys.stdout.write("A matching letter.\n```letter\n" + text + "\n```\n")
else:
    sample = (example / "cv.md").read_text(encoding="utf-8").strip()
    sys.stdout.write("The page, in the CV's look.\n```template\n" + text + "\n```\n```cv\n" + sample + "\n```\n")
