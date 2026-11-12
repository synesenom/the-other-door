"""`compile` and the CV photo (#605): the tailor writes `<<photo>>`; `compile` copies the profile's photo
beside the .tex and puts the one `\\includegraphics` in itself, where the country's conventions allow it."""

import io
import json
import subprocess

import pytest
from PIL import Image

from door.commands import compile as compile_cmd
from door.core import workspace
from door.tailoring import tex_guard

_BOX = "\\newcommand{\\cvphotobox}[1]{#1}"


class _Done:
    returncode = 0
    stderr = ""


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A profile with a photo and a job folder; `built` collects the .tex LaTeX was handed."""
    profile = tmp_path / "profile"
    profile.mkdir()
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "tan").save(buf, "JPEG")
    (profile / "photo.jpg").write_bytes(buf.getvalue())
    (profile / "config.json").write_text(json.dumps({"location": "Copenhagen", "photo": str(profile / "photo.jpg")}))
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)
    built = []

    def run(argv, **kw):
        built.append(open(argv[-1], encoding="utf-8").read())
        return _Done()

    monkeypatch.setattr(subprocess, "run", run)
    jobs = tmp_path / "jobs"
    out = jobs / "output" / "job1"
    out.mkdir(parents=True)

    def make(body, *, location="Copenhagen", preamble=_BOX):
        (out / "posting.json").write_text(json.dumps({"title": "T", "company": "C", "location": location}))
        (out / "cv.tex").write_text(f"\\documentclass{{article}}{preamble}\\begin{{document}}{body}\\end{{document}}\n", encoding="utf-8")
        return jobs

    return type("World", (), {"make": staticmethod(make), "out": out, "built": built, "profile": profile})


def test_the_placeholder_becomes_the_macro_with_the_copied_file(world):
    jobs = world.make("<<photo>>Body")
    result = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"][0]
    assert result["status"] == "compiled"
    assert (world.out / "photo.jpg").read_bytes() == (world.profile / "photo.jpg").read_bytes()
    assert "\\cvphotobox{\\includegraphics" in world.built[0] and "{photo.jpg}" in world.built[0]
    assert "<<photo>>" not in world.built[0]


def test_the_tex_on_disk_keeps_the_placeholder_so_a_recompile_passes_the_guard(world):
    jobs = world.make("<<photo>>Body")
    compile_cmd._compile_core("job1", jobs_dir=jobs)
    assert "<<photo>>" in (world.out / "cv.tex").read_text(encoding="utf-8")
    assert "includegraphics" not in (world.out / "cv.tex").read_text(encoding="utf-8")
    assert compile_cmd._compile_core("job1", jobs_dir=jobs)["results"][0]["status"] == "compiled"


def test_no_photo_in_the_profile_means_nothing_in_the_cv(world):
    (world.profile / "config.json").write_text(json.dumps({"location": "Copenhagen"}))
    jobs = world.make("<<photo>>Body")
    compile_cmd._compile_core("job1", jobs_dir=jobs)
    assert "includegraphics" not in world.built[0] and "<<photo>>" not in world.built[0]
    assert not (world.out / "photo.jpg").exists()


def test_a_country_that_wants_no_photo_gets_none_even_if_the_tailor_wrote_the_placeholder(world):
    jobs = world.make("<<photo>>Body", location="London, United Kingdom")
    compile_cmd._compile_core("job1", jobs_dir=jobs)
    assert "includegraphics" not in world.built[0] and not (world.out / "photo.jpg").exists()


def test_an_older_template_without_the_macro_prints_no_photo(world):
    jobs = world.make("<<photo>>Body", preamble="")
    result = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"][0]
    assert result["status"] == "compiled"
    assert "includegraphics" not in world.built[0] and "cvphotobox" not in world.built[0]
    assert not (world.out / "photo.jpg").exists()


def test_a_photo_that_is_not_a_picture_is_left_out(world):
    (world.profile / "photo.jpg").write_bytes(b"%PDF-1.4")
    jobs = world.make("<<photo>>Body")
    compile_cmd._compile_core("job1", jobs_dir=jobs)
    assert "includegraphics" not in world.built[0] and not (world.out / "photo.jpg").exists()


def test_only_the_first_placeholder_gets_the_photo(world):
    jobs = world.make("<<photo>>A<<photo>>B")
    compile_cmd._compile_core("job1", jobs_dir=jobs)
    assert world.built[0].count("\\includegraphics") == 1


def test_a_job_without_a_country_follows_the_profile_s(world):
    jobs = world.make("<<photo>>Body", location="Remote")
    compile_cmd._compile_core("job1", jobs_dir=jobs)
    assert "\\includegraphics" in world.built[0]


@pytest.mark.parametrize("body", [
    "\\includegraphics{photo.jpg}Body",
    "<<photo>>\\includegraphics{/etc/passwd}",
    "\\includegraphics[width=1cm]{../../profile/config.json}",
])
def test_model_written_includegraphics_is_still_refused(world, body):
    jobs = world.make(body)
    result = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"][0]
    assert result["status"] == "error" and "\\includegraphics" in result["stderr"]
    assert world.built == [] and not (world.out / "photo.jpg").exists()


def test_the_guard_itself_names_includegraphics():
    assert tex_guard.unsafe("\\includegraphics{x.jpg}") == ["\\includegraphics"]


def test_a_preamble_that_names_the_token_in_a_comment_still_gets_the_photo_in_the_body(world):
    jobs = world.make("<<photo>>Body", preamble=_BOX + "\n% the tailor writes <<photo>> where it wants the photo\n")
    result = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"][0]
    assert result["photo"] == "photo.jpg"
    body = world.built[0].split("\\begin{document}", 1)[1]
    assert "\\cvphotobox{\\includegraphics" in body


def test_a_token_only_in_a_preamble_comment_is_no_photo(world):
    jobs = world.make("Body", preamble=_BOX + "\n% the tailor writes <<photo>> where it wants the photo\n")
    result = compile_cmd._compile_core("job1", jobs_dir=jobs)["results"][0]
    assert "photo" not in result and not (world.out / "photo.jpg").exists()
