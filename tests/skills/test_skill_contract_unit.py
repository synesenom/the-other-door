"""The skills and agents under .claude/ name only tools the door MCP server has, with its parameters (#33).

A skill is prose the model follows, so a renamed tool or parameter breaks a conversation, never a test,
unless this one reads them. The server's tools come from `app/src/generated/tools.json`, which
`tests/commands/test_mcp_server.py` keeps equal to the server.
"""

import json
import re

import pytest

from paths import REPO_ROOT

_TOOLS = {t["name"]: set(t["inputSchema"].get("properties", {}))
          for t in json.loads((REPO_ROOT / "app" / "src" / "generated" / "tools.json").read_text(encoding="utf-8"))}
_FILES = sorted([*(REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md"), *(REPO_ROOT / ".claude" / "agents").glob("*.md")])
_TOOL = re.compile(r"mcp__door__(\w+)")
# "`mcp__door__keywords` with the recommended titles as `role_targets` and `languages`": the backticked words
# after "as", "with" or "pass" in the sentence that names the tool.
_ARG = re.compile(r"\b(?:as|with|pass|passing)\s+`(\w+)`((?:\s*(?:,|and|or)\s*`\w+`)*)")
_MORE = re.compile(r"`(\w+)`")


def _id(path) -> str:
    return str(path.relative_to(REPO_ROOT))


def named_tools(text: str) -> set[str]:
    return set(_TOOL.findall(text))


def named_arguments(text: str) -> list[tuple[str, str]]:
    """``(tool, argument)`` for each argument a sentence passes to the one tool it names."""
    out = []
    for sentence in re.split(r"(?<=[.;:])\s+(?=[A-Z(`])|\n\s*\n|\n\s*[-*] ", text):
        sentence = " ".join(sentence.split())
        tools = set(_TOOL.findall(sentence))
        if len(tools) != 1:
            continue
        tool = tools.pop()
        after = sentence.split(f"mcp__door__{tool}", 1)[1]
        for first, rest in _ARG.findall(after):
            out += [(tool, a) for a in (first, *_MORE.findall(rest)) if a not in _TOOLS]   # "with `find_jobs`": a tool, not an argument
    return out


def test_the_reader_finds_a_tool_and_the_arguments_a_sentence_passes_it():
    text = "Call `mcp__door__keywords` with the recommended titles as `role_targets` and `languages`. Then stop."
    assert named_tools(text) == {"keywords"}
    assert named_arguments(text) == [("keywords", "role_targets"), ("keywords", "languages")]


def test_a_tool_named_after_with_is_not_an_argument():
    assert named_arguments("Call `mcp__door__sync_data`; the user starts one with `find_jobs` when they want.") == []


def test_a_sentence_naming_two_tools_passes_no_arguments_to_either():
    assert named_arguments("Call `mcp__door__a` then `mcp__door__b` with `x`.") == []


def test_there_are_skills_to_read():
    assert any(named_tools(p.read_text(encoding="utf-8")) for p in _FILES)


@pytest.mark.parametrize("path", _FILES, ids=_id)
def test_every_tool_a_skill_names_is_a_server_tool(path):
    unknown = named_tools(path.read_text(encoding="utf-8")) - set(_TOOLS)
    assert not unknown, f"{_id(path)} names tools the server does not have: {sorted(unknown)}"


@pytest.mark.parametrize("path", _FILES, ids=_id)
def test_every_argument_a_skill_passes_is_a_parameter_of_its_tool(path):
    wrong = [(t, a) for t, a in named_arguments(path.read_text(encoding="utf-8")) if t in _TOOLS and a not in _TOOLS[t]]
    assert not wrong, f"{_id(path)} passes arguments its tools do not take: {wrong}"
