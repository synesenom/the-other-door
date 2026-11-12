"""`src/door/commands/_prompts.py`: the inquirer wrapper behind `init`'s prompts."""

import pytest
from inquirer.errors import ValidationError
from inquirer.questions import TaggedValue

from door.commands import _prompts


@pytest.fixture
def answer(monkeypatch):
    """Answer the next inquirer prompt with `value`; returns the questions asked."""
    asked = []

    def set_answer(value):
        def prompt(questions, raise_keyboard_interrupt):
            assert raise_keyboard_interrupt  # Ctrl-C aborts instead of answering None
            asked.extend(questions)
            return {questions[0].name: value}
        monkeypatch.setattr(_prompts.inquirer, "prompt", prompt)
        return asked

    return set_answer


def test_select_returns_the_choice_value(answer):
    asked = answer(TaggedValue("Copenhagen (Denmark)", "Copenhagen"))
    choice = _prompts.select("location", "Location", [("Copenhagen (Denmark)", "Copenhagen")], default="Copenhagen")
    assert choice == "Copenhagen"
    assert asked[0].default == "Copenhagen"


def test_checkbox_returns_the_choice_values(answer):
    answer([TaggedValue("linkedin (needs a login)", "linkedin")])
    assert _prompts.checkbox("sites", "Sites", [("linkedin (needs a login)", "linkedin")]) == ["linkedin"]


def test_text_and_confirm_pass_the_answer_through(answer):
    answer("Jane")
    assert _prompts.text("name", "Name") == "Jane"
    answer(True)
    assert _prompts.confirm("overwrite", "Edit?") is True


def test_validate_message_becomes_an_inquirer_validation_error(answer):
    asked = answer("0.5")
    _prompts.text("min_score", "Score", validate=lambda v: None if v == "0.5" else "bad")
    check = asked[0]._validate
    assert check({}, "0.5") is True
    with pytest.raises(ValidationError):
        check({}, "x")
