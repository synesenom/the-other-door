"""The CV style builder end to end (#149): a canned stylist (the model seam) on corpus PDFs, the real Chromium print
and the real stress renders, fonts from a stand-in download. Marked `real_chromium` like test_template_print.py."""

import json
import os
import re
import shutil

import pytest

from door.core import chromium, claude_cli, fonts, templates
from door.tailoring import cv_body, html_guard, style_build
from paths import REPO_ROOT, TESTS_DIR

pytestmark = [
    pytest.mark.real_chromium,
    pytest.mark.skipif(chromium.find_chromium() is None and not os.environ.get("CI"),
                       reason="no Chromium headless shell installed"),
]

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"
EXAMPLE = REPO_ROOT / "profile.example"
BIG = "body { font-size: 30pt !important; }"  # makes the compact stress variant run over the page limit


def _families(css):
    return re.findall(r'font-family: "([^"]+)"', css)


def _adapt(path, css, extra=""):
    """The shipped template `path` with the fonts the builder gave (`fonts.css`) in place of its own."""
    text = (EXAMPLE / path).read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.startswith("@font-face"))
    names = _families(css)
    text = text.replace("Figtree, sans-serif", f'"{names[0]}", sans-serif').replace('"Young Serif", serif', f'"{names[-1]}", serif')
    return text.replace("<style>", "<style>\n" + css + "\n", 1).replace("</style>", extra + "\n</style>", 1)


def _reply(template, body=None):
    text = "I see a page.\n```template\n" + template + "\n```\n"
    return text + (f"```body\n{body}\n```\n" if body else "")


SAMPLE_BODY = cv_body.body((EXAMPLE / "cv.md").read_text(encoding="utf-8"))


class Stylist:
    """The model seam: each call takes the next reply, a string or a function of the call's folder (to read fonts.css)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, args, *, feature, input=None, timeout_s=None, profile_dir=None, cwd=None):
        self.calls.append({"args": args, "feature": feature, "input": input, "cwd": cwd})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        text = reply(cwd) if callable(reply) else reply
        return json.dumps({"type": "result", "result": text, "total_cost_usd": 0.01})


def cv_round(extra="", body=SAMPLE_BODY):
    return lambda cwd: _reply(_adapt("cv.template.html", (cwd / "fonts.css").read_text(), extra), body)


def cv_only(extra=""):
    return lambda cwd: _reply(_adapt("cv.template.html", (cwd / "fonts.css").read_text(), extra))


def letter_round():
    return lambda cwd: "A letter.\n```letter\n" + _adapt("cover-letter.template.html", (cwd / "fonts.css").read_text()) + "\n```\n"


def fake_fonts(plan, dest):
    """A stand-in for the download: every file of the plan is the shipped Figtree regular."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for entry in plan:
        for f in entry["files"]:
            shutil.copyfile(EXAMPLE / "fonts" / "Figtree-Regular.ttf", dest / f["name"])
            out.append(dest / f["name"])
    return out


@pytest.fixture
def world(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    return profile, tmp_path / "work"


def run_build(world, pdf, stylist, **kw):
    profile, work = world
    kw.setdefault("fonts_fetch", fake_fonts)
    return style_build.build(STYLES / f"{pdf}.pdf", profile_dir=profile, work_dir=work, run=stylist, **kw)


def test_a_good_template_builds_and_is_written_whole(world):
    profile, work = world
    stylist = Stylist(cv_round(), cv_only(), letter_round())
    result = run_build(world, "html-word-two-column", stylist)
    assert result["state"] == "ready", result["problems"]
    assert result["problems"] == [] and result["rounds"] >= 2 and 0 <= result["score"] <= 1
    assert result["rounds"] == len(stylist.calls) - 1  # the letter's call is not a round of the CV template
    assert result["scores"] and result["score"] == max(result["scores"])
    assert {f["family"] for f in result["fonts"]} == {"Figtree", "Young Serif"}
    style = profile / "style"
    assert sorted(p.name for p in style.iterdir()) == ["cover-letter.template.html", "cv.template.html", "fonts", "source.pdf",
                                                      "style.json", "template.json"]
    manifest = templates.manifest(style / "cv.template.html")
    assert manifest.max_pages == 1 and manifest.columns.side  # a one page CV with a side column
    assert set(manifest.fonts) <= {p.name for p in (style / "fonts").iterdir()}
    assert templates.assets(style / "cv.template.html")["fonts"]
    assert html_guard.template_problems((style / "cv.template.html").read_text(), manifest) == []
    assert html_guard.template_problems((style / "cover-letter.template.html").read_text(), manifest, "letter") == []
    assert (style / "source.pdf").read_bytes() == (STYLES / "html-word-two-column.pdf").read_bytes()
    assert not [p for p in profile.iterdir() if p.name != "style"]  # nothing staged is left


def test_every_model_call_is_a_read_only_stylist_run_in_the_work_folder_named_style(world):
    profile, work = world
    stylist = Stylist(cv_round(), cv_only(), letter_round())
    run_build(world, "html-word-two-column", stylist)
    assert {c["feature"] for c in stylist.calls} == {"style"}
    assert {c["cwd"] for c in stylist.calls} == {work}
    args = stylist.calls[0]["args"]
    assert args[args.index("--agent") + 1] == "stylist" and "--restricted" in args
    agents = json.loads(args[args.index("--agents") + 1])
    assert agents["stylist"]["model"] == "sonnet" and agents["stylist"]["tools"] == ["Read"]
    assert "original_page_1.png" in stylist.calls[0]["input"] and "Page limit: 1" in stylist.calls[0]["input"]
    assert (work / "original_page_1.png").is_file() and (work / "style.json").is_file()


def test_a_template_the_guard_refuses_is_not_printed_and_the_next_round_is_told_why(world):
    profile, work = world
    bad = lambda cwd: _reply(_adapt("cv.template.html", (cwd / "fonts.css").read_text()).replace("</head>", "<script>1</script></head>"), SAMPLE_BODY)
    stylist = Stylist(bad, cv_only(), cv_only(), letter_round())
    result = run_build(world, "html-word-two-column", stylist)
    assert result["state"] == "ready"
    assert "guard refused" in stylist.calls[1]["input"] and "<script>" in stylist.calls[1]["input"]
    assert "```body" not in stylist.calls[1]["input"]  # the body of round 1 was fine: it is fixed
    assert len(result["scores"]) >= 1 and result["rounds"] >= 3


def test_a_template_that_fails_the_stress_renders_gets_one_more_round(world):
    profile, work = world
    stylist = Stylist(cv_round(BIG), cv_round(BIG), cv_only(), letter_round())
    result = run_build(world, "html-word-two-column", stylist)
    assert result["state"] == "ready", result["problems"]
    extra = [c for c in stylist.calls if "stress" in c["input"] or "fails" in c["input"]]
    assert extra and "fewer" in extra[0]["input"]
    assert BIG not in (profile / "style" / "cv.template.html").read_text()


def test_a_template_that_still_fails_after_the_extra_round_is_failed_and_writes_nothing(world):
    profile, work = world
    stylist = Stylist(cv_round(BIG), cv_only(BIG), cv_only(BIG), cv_only(BIG), letter_round())
    result = run_build(world, "html-word-two-column", stylist)
    assert result["state"] == "failed"
    assert any("stress" in p and "fewer" in p for p in result["problems"])
    assert not (profile / "style").exists() and list(profile.iterdir()) == []


def test_a_stylist_that_never_gives_a_template_fails(world):
    stylist = Stylist("I cannot do that.")
    result = run_build(world, "html-word-two-column", stylist, cap=3)
    assert result["state"] == "failed" and result["rounds"] == 3 and "3 rounds" in result["problems"][0]
    assert not (world[0] / "style").exists()


def test_a_model_error_is_a_failed_result_not_an_exception(world):
    def boom(args, **kw):
        raise claude_cli.ClaudeError("claude exited 1: no plan")
    result = run_build(world, "html-word-two-column", boom)
    assert result["state"] == "failed" and "no plan" in result["problems"][0]
    assert not (world[0] / "style").exists()


@pytest.mark.parametrize("pdf", ["scan", "linkedin-like"])
def test_a_cv_with_no_style_to_copy_fails_without_asking_the_model(world, pdf):
    stylist = Stylist("unused")
    result = run_build(world, pdf, stylist)
    assert result["state"] == "failed" and result["problems"] and stylist.calls == []


def test_a_file_that_is_not_a_pdf_fails_without_asking_the_model(world, tmp_path):
    word = tmp_path / "cv.docx"
    word.write_bytes(b"PK")
    stylist = Stylist("unused")
    result = style_build.build(word, profile_dir=world[0], work_dir=world[1], run=stylist)
    assert result["state"] == "failed" and "docx" in result["problems"][0] and stylist.calls == []


def test_a_font_download_that_fails_falls_back_to_the_shipped_fonts_and_says_so(world):
    profile, work = world

    def broken(plan, dest):
        raise fonts.FontsError("offline")

    stylist = Stylist(cv_round(), cv_only(), letter_round())
    result = run_build(world, "html-word-two-column", stylist, fonts_fetch=broken)
    assert result["state"] == "ready" and result["font_error"] == "offline"
    assert {f["source"] for f in result["fonts"]} == {"shipped"}
    manifest = templates.manifest(profile / "style" / "cv.template.html")
    assert "Figtree-Regular.ttf" in manifest.fonts and "YoungSerif-Regular.ttf" in manifest.fonts
    assert "Figtree-Regular.ttf" in (work / "fonts.css").read_text()


def test_a_font_with_no_free_copy_builds_anyway_and_is_named(world, monkeypatch):
    entry = {"family": "Mystery Sans", "source": "none", "resolved": None, "reason": "Mystery Sans: no free copy is close enough",
             "faked": [], "files": [], "licence": None, "alternatives": [], "uses": []}
    monkeypatch.setattr(fonts, "plan", lambda *a, **k: [entry])
    stylist = Stylist(lambda cwd: _reply(_adapt("cv.template.html", _shipped_css()), SAMPLE_BODY), lambda cwd: _reply(_adapt("cv.template.html", _shipped_css())),
                      lambda cwd: "```letter\n" + _adapt("cover-letter.template.html", _shipped_css()) + "\n```")
    result = run_build(world, "html-word-two-column", stylist)
    assert result["fonts"][0]["family"] == "Mystery Sans" and result["fonts"][0]["source"] == "none"
    assert "no font" in stylist.calls[0]["input"].lower() or "generic" in stylist.calls[0]["input"]
    assert result["state"] in ("ready", "failed")


def _shipped_css():
    return "@font-face { font-family: \"Figtree\"; src: url(/fonts/Figtree-Regular.ttf) format(\"truetype\"); }"


def test_icons_found_in_the_cv_are_written_by_kind_and_the_others_named(world):
    profile, work = world
    stylist = Stylist(cv_round(), cv_only(), letter_round())
    result = run_build(world, "scrubbed-altacv-icons-fr", stylist)
    assert result["state"] == "ready", result["problems"]
    manifest = templates.manifest(profile / "style" / "cv.template.html")
    assert {"email", "phone"} <= set(manifest.icons)
    assert all((profile / "style" / "icons" / name).is_file() for name in manifest.icons.values())
    assert result["dropped_icons"] and all(set(d) == {"near", "reason"} for d in result["dropped_icons"])


def test_a_rebuild_replaces_the_earlier_style_whole(world):
    profile, work = world
    (profile / "style").mkdir()
    (profile / "style" / "stale.txt").write_text("old")
    stylist = Stylist(cv_round(), cv_only(), letter_round())
    assert run_build(world, "html-word-two-column", stylist)["state"] == "ready"
    assert not (profile / "style" / "stale.txt").exists()


def test_a_failed_rebuild_leaves_the_earlier_style_alone(world):
    profile, work = world
    (profile / "style").mkdir()
    (profile / "style" / "keep.txt").write_text("old")
    result = run_build(world, "html-word-two-column", Stylist("no"), cap=2)
    assert result["state"] == "failed" and (profile / "style" / "keep.txt").read_text() == "old"


def test_progress_is_reported_through_the_reporter(world):
    events = []

    class Reporter:
        def report(self, event):
            events.append((event.stage, event.message))

    run_build(world, "html-word-two-column", Stylist(cv_round(), cv_only(), letter_round()), progress=Reporter())
    assert ("style", "building the letter template") in events
    assert any(m.startswith("building the template, round") for _, m in events)
