"""The facts check on the example profile's realistic prepared CV and letter (the model's answer stubbed)."""

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
    shutil.copy(FIXTURES / "example_cv.html", out / "cv.html")
    shutil.copy(FIXTURES / "example_cover_letter.html", out / "cover_letter.html")
    shutil.copy(FIXTURES / "example_posting.json", out / "posting.json")
    return out, prof


def test_example_materials_are_clean_when_the_model_finds_nothing(example):
    out, prof = example
    assert facts.check(out, prof, write=False) == []


def test_the_model_is_shown_the_example_and_its_finding_is_held_to_the_text(example, monkeypatch):
    out, prof = example
    shown = []
    quote = "SAP S/4HANA Finance"
    assert quote in (out / "cv.html").read_text()

    def ask(inputs):
        shown.append(inputs)
        return {"findings": [{"kind": "skill", "value": "Terraform", "context": quote, "file": "cv"},
                             {"kind": "skill", "value": "Rust", "context": "Rust in production", "file": "cv"}]}

    monkeypatch.setattr(facts, "_ask", ask)
    found = facts.check(out, prof, write=False)
    assert [f["value"] for f in found] == ["Terraform"] and len(shown) == 1
