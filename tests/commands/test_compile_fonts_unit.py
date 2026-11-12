"""`compile` and the templates' fonts (#623): a template loads its fonts from `<<fonts>>`, which `compile` swaps
for the profile's `fonts/` folder (the example's when the profile has none) only while LaTeX runs; the .tex on
disk keeps the token, so a job folder carries no path of this computer and no copy of the fonts."""

import json
import subprocess

import pytest

from door.commands import compile as compile_cmd
from door.core import workspace

_PREAMBLE = "\\setmainfont{Figtree-Regular.otf}[Path=<<fonts>>/]"


class _Done:
    returncode = 0
    stderr = ""


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A profile and a job folder; `built` collects the .tex LaTeX was handed."""
    profile = tmp_path / "profile"
    profile.mkdir()
    example = tmp_path / "profile.example"
    (example / "fonts").mkdir(parents=True)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", example)
    monkeypatch.setattr(compile_cmd, "_find_tectonic", lambda: None)
    built = []

    def run(argv, **kw):
        built.append(open(argv[-1], encoding="utf-8").read())
        return _Done()

    monkeypatch.setattr(subprocess, "run", run)
    jobs = tmp_path / "jobs"
    out = jobs / "output" / "job1"
    out.mkdir(parents=True)
    (out / "posting.json").write_text(json.dumps({"title": "T", "company": "C", "location": "Copenhagen"}))

    def make(preamble=_PREAMBLE):
        (out / "cv.tex").write_text(f"\\documentclass{{article}}{preamble}\\begin{{document}}Body\\end{{document}}\n", encoding="utf-8")
        return jobs

    return type("World", (), {"make": staticmethod(make), "out": out, "built": built, "profile": profile, "example": example})


def test_the_token_becomes_the_profiles_fonts_folder_while_latex_runs(world):
    (world.profile / "fonts").mkdir()
    result = compile_cmd._compile_core("job1", jobs_dir=world.make())["results"][0]
    assert result["status"] == "compiled"
    assert f"Path={(world.profile / 'fonts').as_posix()}/" in world.built[0]
    assert "<<fonts>>" in (world.out / "cv.tex").read_text(encoding="utf-8")


def test_a_profile_without_fonts_uses_the_examples(world):
    compile_cmd._compile_core("job1", jobs_dir=world.make())
    assert f"Path={(world.example / 'fonts').as_posix()}/" in world.built[0]


def test_a_template_without_the_token_is_handed_over_unchanged(world):
    jobs = world.make(preamble="\\usepackage{xcolor}")
    compile_cmd._compile_core("job1", jobs_dir=jobs)
    assert world.built[0] == (world.out / "cv.tex").read_text(encoding="utf-8")
