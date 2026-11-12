"""The `jobs` group: your list of postings, viewed and edited by hand.

`jobs` alone is `jobs list`, the matches you haven't acted on, best first; `show`, `add`, `status`,
`summary`, `prepare`, `query` and `salary` are the verbs. Each subcommand and its `_<name>_core` live in their own module
(`matches.py`, `add.py`, `status.py`, `prepare.py`); this module only assembles the group.
"""

import click

from door.commands import add as add_cmd
from door.commands import matches as matches_cmd
from door.commands import prepare as prepare_cmd
from door.commands import query as query_cmd
from door.commands import salary as salary_cmd
from door.commands import status as status_cmd


@click.group("jobs", invoke_without_command=True)
@click.pass_context
def jobs_group(ctx: click.Context):
    """Your postings: ranked matches, and the verbs to work on one.

    `jobs` alone is `jobs list` with no filters (the matches you haven't acted on, best first;
    `jobs list --help` has the filters); `show`, `add`, `status` and `prepare` read, bring
    in, track and tailor one; `summary` is the dashboard."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(matches_cmd.list_matches, score=None, new_only=False, status=None, ongoing=False)


jobs_group.add_command(matches_cmd.list_matches, "list")
jobs_group.add_command(matches_cmd.show, "show")
jobs_group.add_command(add_cmd.add, "add")
jobs_group.add_command(status_cmd.status, "status")
jobs_group.add_command(status_cmd.summary, "summary")
jobs_group.add_command(prepare_cmd.prepare, "prepare")
jobs_group.add_command(query_cmd.query, "query")
jobs_group.add_command(salary_cmd.salary_cmd, "salary")
