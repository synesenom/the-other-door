"""Stand-ins and canned replies for the CV style builder's tests (#149): the model seam (`Stylist`), the font download
(`fake_fonts`) and the replies of a stylist that writes the shipped templates over the fonts the builder gave."""

import json
import re
import shutil

from door.tailoring import cv_body
from paths import REPO_ROOT, TESTS_DIR

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"
EXAMPLE = REPO_ROOT / "profile.example"
BIG = "body { font-size: 30pt !important; }"  # makes the compact stress variant run over the page limit
# the shipped template is one column: the canned stylist places a corpus CV's side column on the right, as
# html-word-two-column has it (a print with its side sections under the main ones is refused, #242)
COLUMNS = "body { display: grid; grid-template-columns: 1fr 34%; column-gap: 1.2em; } body > .cv-header { grid-column: 1 / -1; }"
SAMPLE_BODY = cv_body.body((EXAMPLE / "cv.md").read_text(encoding="utf-8"))


class Stylist:
    """The model seam: each call takes the next reply (the last one repeats), a string or a function of the call's folder."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, args, *, feature, input=None, timeout_s=None, profile_dir=None, cwd=None):
        self.calls.append({"args": args, "feature": feature, "input": input, "cwd": cwd})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        text = reply(cwd) if callable(reply) else reply
        return json.dumps({"type": "result", "result": text, "total_cost_usd": 0.01})


def adapt(path, css, extra=""):
    """The shipped template `path` with the fonts the builder gave (`fonts.css`) in place of its own."""
    text = (EXAMPLE / path).read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.startswith("@font-face"))
    names = re.findall(r'font-family: "([^"]+)"', css)
    if names:
        text = text.replace("Figtree, sans-serif", f'"{names[0]}", sans-serif').replace('"Young Serif", serif', f'"{names[-1]}", serif')
    return text.replace("<style>", "<style>\n" + css + "\n", 1).replace("</style>", extra + "\n</style>", 1)


def reply(template, body=None):
    text = "I see a page.\n```template\n" + template + "\n```\n"
    return text + (f"```body\n{body}\n```\n" if body else "")


def _cv(cwd, extra, edit):
    return edit(adapt("cv.template.html", (cwd / "fonts.css").read_text(), COLUMNS + "\n" + extra))


def cv_round(extra="", body=SAMPLE_BODY, edit=lambda t: t):
    return lambda cwd: reply(_cv(cwd, extra, edit), body)


def cv_only(extra="", edit=lambda t: t):
    return lambda cwd: reply(_cv(cwd, extra, edit))


def letter_round(extra="", edit=lambda t: t):
    return lambda cwd: ("A letter.\n```letter\n"
                        + edit(adapt("cover-letter.template.html", (cwd / "fonts.css").read_text(), extra)) + "\n```\n")


def fake_fonts(plan, dest):
    """A stand-in for the download: every file of the plan is the shipped Figtree regular."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for entry in plan:
        for f in entry["files"]:
            shutil.copyfile(EXAMPLE / "fonts" / "Figtree-Regular.ttf", dest / f["name"])
            out.append(dest / f["name"])
    return out
