"""The top-level help: sections in a fixed order, each command with its subcommands; the
`jobs` group and the old top-level commands that moved into it."""

import re

from click.testing import CliRunner

from door.cli import cli


def _help(*args):
    return CliRunner().invoke(cli, [*args, "--help"]).output


def test_top_level_help_is_sectioned_in_order():
    out = _help()
    sections = re.findall(r"^(Set up|Find|Your lists|Your CV|Move|Other|Commands):$", out, re.MULTILINE)
    assert sections == ["Set up", "Find", "Your lists", "Your CV", "Move"]
    for line in (
        "init", "doctor",
        "find",
        "jobs [show|add|status|summary|prepare|query|salary]",
        "ask",
        "companies [why|add|remove|merge]",
        "cv [enrich|gaps|titles|stories]",
        "data [export|import|connect|sync|disconnect|report]",
    ):
        assert re.search(rf"^  {re.escape(line)}\s", out, re.MULTILINE), line
    order = [out.index(f"\n  {name}") for name in ("init", "doctor", "find", "jobs", "companies", "ask", "cv", "data")]
    assert order == sorted(order)

