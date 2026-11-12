"""Interactive terminal prompts, on inquirer: free text, one of a list, several
of a list, and yes/no; and one key out of a few (on click).

Every prompt takes a `name`; tests replace these five functions with scripted
answers keyed by it (see tests/commands/test_init_cli.py), since inquirer reads
keys from a real terminal. `choices` are ``(label, value)`` pairs; the value is
what comes back. `validate` takes the answer and returns an error message, or
``None`` when it is fine. Ctrl-C raises ``KeyboardInterrupt``, which Click
reports as "Aborted!".
"""

from collections.abc import Callable, Sequence

import inquirer
from inquirer.errors import ValidationError

Choices = Sequence[tuple[str, object]]


def _validator(validate: Callable[[object], str | None] | None):
    if validate is None:
        return True

    def check(_answers, current):
        error = validate(current)
        if error:
            raise ValidationError(current, reason=error)
        return True

    return check


def _ask(question):
    answers = inquirer.prompt([question], raise_keyboard_interrupt=True)
    return answers[question.name]


def _value(answer):
    return getattr(answer, "value", answer)


def text(name: str, message: str, default: str = "", validate=None) -> str:
    return _ask(inquirer.Text(name, message=message, default=default, validate=_validator(validate)))


def select(name: str, message: str, choices: Choices, default=None):
    return _value(_ask(inquirer.List(name, message=message, choices=list(choices), default=default, carousel=True)))


def checkbox(name: str, message: str, choices: Choices, default: Sequence = (), validate=None) -> list:
    question = inquirer.Checkbox(
        name, message=message, choices=list(choices), default=list(default), validate=_validator(validate)
    )
    return [_value(answer) for answer in _ask(question)]


def confirm(name: str, message: str, default: bool = False) -> bool:
    return _ask(inquirer.Confirm(name, message=message, default=default))


def key(name: str, message: str, keys: dict[str, str], default: str) -> str:
    """One keypress out of ``keys`` (key -> label), shown as ``[d] description · [q] quit``;
    Enter (or no input left) is `default`, any other key asks again."""
    import click

    menu = " · ".join(f"[{k}] {label}" for k, label in keys.items())
    while True:
        click.echo(f"{message}{menu} ", nl=False)
        pressed = click.getchar()
        if pressed in ("", "\r", "\n"):
            pressed = default
        if pressed == "\x03":
            raise KeyboardInterrupt
        click.echo(pressed if pressed in keys else "")
        if pressed in keys:
            return pressed
