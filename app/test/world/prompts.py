"""Scripted answers for `door init`'s five prompt functions (door.commands._prompts), for the CLI journeys.

inquirer reads keys from a real terminal, so the journeys script the wizard as the unit tests do: the
answers live in the world, `<world>/prompts.json` (`{name: {"answer": X}}` or `{name: {"sequence": [a, b]}}`),
read on every call; a name with no answer gets the call's `default`. The CLI is a fresh process per command,
so the place in a sequence is kept in `<world>/prompts-state.json`. Every ask is logged to `calls.jsonl`. A name
asked more than `MAX_ASKS` times in one process ends it: a wizard that cannot go on (a draft that failed) would
ask again with the same default forever.
"""

import json
import time
from pathlib import Path

MAX_ASKS = 25


def install(module, world: Path) -> None:
    world = Path(world)
    asked: dict[str, int] = {}

    def script() -> dict:
        try:
            return json.loads((world / "prompts.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def log(name: str) -> None:
        with (world / "calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "prompt", "name": name, "at": time.time()}) + "\n")

    def answer(name: str, default):
        log(name)
        asked[name] = asked.get(name, 0) + 1
        if asked[name] > MAX_ASKS:
            raise SystemExit(f"the test world: {name!r} asked {MAX_ASKS} times, the wizard is looping")
        said = script().get(name)
        if not said:
            return default
        if "answer" in said:
            return said["answer"]
        seq = said.get("sequence", [])
        state_file = world / "prompts-state.json"
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        at = state.get(name, 0)
        state[name] = at + 1
        state_file.write_text(json.dumps(state), encoding="utf-8")
        return seq[at] if at < len(seq) else default

    def text(name, message, default="", validate=None, **_):
        return answer(name, default)

    def select(name, message, choices, default=None, **_):
        return answer(name, default)

    def checkbox(name, message, choices, default=(), validate=None, **_):
        value = answer(name, default)
        return list(value) if value is not None else []

    def confirm(name, message, default=False, **_):
        return answer(name, default)

    def key(name, message, keys, default, **_):
        return answer(name, default)

    module.text, module.select, module.checkbox, module.confirm, module.key = text, select, checkbox, confirm, key
