"""The facts check on the example profile's realistic prepared CV and letter: no false positives."""

import json
import shutil

import pytest

from door.tailoring import facts
from tests.paths import REPO_ROOT, TESTS_DIR

FIXTURES = TESTS_DIR / "tailoring" / "fixtures"


@pytest.fixture
def example(tmp_path):
    out, prof = tmp_path / "out", tmp_path / "profile"
    out.mkdir(), prof.mkdir()
    shutil.copy(REPO_ROOT / "profile.example" / "cv.md", prof / "cv.md")
    shutil.copy(FIXTURES / "example_cv.tex", out / "cv.tex")
    shutil.copy(FIXTURES / "example_cover_letter.tex", out / "cover_letter.tex")
    shutil.copy(FIXTURES / "example_posting.json", out / "posting.json")
    return out, prof


def test_example_materials_are_clean(example):
    out, prof = example
    assert facts.check(out, prof, write=False, current_year=2026) == []


def test_demo_stub_materials_are_clean(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("demo_shim", REPO_ROOT / "scripts" / "demo" / "shim.py")
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)

    prof = tmp_path / "profile"
    prof.mkdir()
    shutil.copy(REPO_ROOT / "profile.example" / "cv.md", prof / "cv.md")
    out = tmp_path / "out"
    out.mkdir()
    (out / "cv.tex").write_text(shim._CV_TEX)
    (out / "cover_letter.tex").write_text(shim._LETTER_TEX % shim._LETTER_BODY)
    assert facts.check(out, prof, write=False, current_year=2026) == []


def test_an_invented_skill_and_certification_are_the_only_findings(example):
    out, prof = example
    cv = (out / "cv.tex").read_text()
    cv = cv.replace("Power BI,\nMicrosoft", "Power BI, Terraform,\nMicrosoft")
    cv = cv.replace("\\item SAP S/4HANA Finance --- 2022", "\\item SAP S/4HANA Finance --- 2022\n\\item PMP Project Management Professional")
    (out / "cv.tex").write_text(cv)
    found = facts.check(out, prof, write=False, current_year=2026)
    assert [(c["kind"], c["value"]) for c in found] == [
        ("skill", "Terraform"), ("certification", "PMP Project Management Professional")]
    assert all(c["context"] for c in found)
