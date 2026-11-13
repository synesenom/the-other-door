"""The Click entry point: the `cli` group with every command registered on it.

Each command, and the `_<name>_core` it wraps, lives in `src/door/commands/`; the MCP
server (`src/door/mcp_server.py`) wraps the same cores.
"""

import sys

import click

from door.commands import _common as common
from door.core import migrations, problem_log
from door.core.lock import LockHeldError
from door.core.profile_loader import ConfigError
from door.commands import archive as archive_cmd
from door.commands import ask as ask_cmd
from door.commands import companies as companies_cmd
from door.commands import cv as cv_cmd
from door.commands import enrich as enrich_cmd
from door.commands import gaps as gaps_cmd
from door.commands import jobs as jobs_cmd
from door.commands import market as market_cmd
from door.commands import profile as profile_cmd
from door.commands import find as find_cmd
from door.commands import report as report_cmd
from door.commands import serve as serve_cmd
from door.commands import setup as setup_cmd
from door.commands import stories as stories_cmd
from door.commands import titles as titles_cmd


class _DoorGroup(click.Group):
    """Renders a `ConfigError` from any command as one line per problem, exit 1, writes a crash to
    the problem log, and lays the help out in sections."""

    def format_commands(self, ctx, formatter):
        listed = set()
        for title, names in _SECTIONS:
            rows = []
            for name in names:
                command = self.commands.get(name)
                if command is None or command.hidden:
                    continue
                listed.add(name)
                rows.append((_command_label(name, command), _first_line(command)))
            if rows:
                with formatter.section(title):
                    formatter.write_dl(rows, col_max=46)
        rest = [
            (name, _first_line(command))
            for name, command in self.commands.items()
            if name not in listed and not command.hidden
        ]
        if rest:
            with formatter.section("Other"):
                formatter.write_dl(rest)

    def resolve_command(self, ctx, args):
        """The command about to run: the data folders are upgraded first (#56), and a refused folder stops every
        command but the ones that let the user report it."""
        if args and "--help" not in args:
            migrations.run_at_start()
            state = migrations.status()
            if state is not None and args[0] not in _DATA_OPEN_COMMANDS and args[:2] != ["data", "report"]:
                click.echo(f"Error: {state['message']}", err=True)
                sys.exit(1)
        return super().resolve_command(ctx, args)

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except ConfigError as exc:
            common._echo_config_error(exc)
            sys.exit(1)
        except LockHeldError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        except (click.ClickException, click.exceptions.Exit, click.Abort):
            raise  # a usage error or an exit on purpose, not a crash
        except Exception as exc:
            problem_log.crash(f"command {ctx.invoked_subcommand}", exc)
            raise


# Commands that still run when the data was refused (a failed upgrade, newer data): doctor says why, and `serve`
# answers its tools with the same refusal.
_DATA_OPEN_COMMANDS = ("doctor", "serve")

# The top-level help, in this order: section -> its commands.
_SECTIONS = (
    ("Set up", ("init", "doctor")),
    ("Find", ("find",)),
    ("Your lists", ("jobs", "companies", "market", "ask")),
    ("Your CV", ("cv",)),
    ("Move", ("data", "serve")),
)
_DEFAULT_SUBCOMMAND = "list"  # a group's bare call; not worth naming in the help line


def _first_line(command: click.Command) -> str:
    return (command.help or "").strip().split("\n")[0]


def _command_label(name: str, command: click.Command) -> str:
    """`jobs [show|add|...]` for a group (its hidden subcommands left out), the bare name for a command."""
    if not isinstance(command, click.Group):
        return name
    subs = [name for name, sub in command.commands.items() if name != _DEFAULT_SUBCOMMAND and not sub.hidden]
    return f"{name} [{'|'.join(subs)}]" if subs else name


@click.group(cls=_DoorGroup)
@click.pass_context
def cli(ctx: click.Context):
    """Automated job hunting pipeline."""
    ctx.call_on_close(_say_what_drive_did)


# A mark per kind of `sync` note; the lines go to stderr, so a pipe of stdout stays clean.
_SYNC_MARKS = {"pulled": ("↓", "cyan"), "pushed": ("↑", "bright_black"), "warning": ("⚠", "yellow")}


def _say_what_drive_did() -> None:
    """Once a command is done: one line per Google Drive pull, push or skipped sync it caused."""
    from door.core import sync

    for kind, message in sync.drain_notes():
        mark, colour = _SYNC_MARKS[kind]
        click.secho(f"{mark} {message}", fg=colour, err=True)


cli.add_command(profile_cmd.init)
cli.add_command(find_cmd.find)
cli.add_command(setup_cmd.doctor)
cli.add_command(jobs_cmd.jobs_group)
cli.add_command(market_cmd.market)
cli.add_command(ask_cmd.ask)

cv_cmd.cv_group.add_command(enrich_cmd.enrich, "enrich")
cv_cmd.cv_group.add_command(gaps_cmd.skill_gaps, "gaps")
cv_cmd.cv_group.add_command(titles_cmd.titles_command, "titles")
cv_cmd.cv_group.add_command(stories_cmd.stories_group, "stories")
cli.add_command(cv_cmd.cv_group)

companies_cmd.companies_group.add_command(companies_cmd.list_companies, "list")
companies_cmd.companies_group.add_command(companies_cmd.why_company, "why")
companies_cmd.companies_group.add_command(companies_cmd.add_company, "add")
companies_cmd.companies_group.add_command(companies_cmd.remove_company, "remove")
companies_cmd.companies_group.add_command(companies_cmd.merge_companies, "merge")
cli.add_command(companies_cmd.companies_group)

archive_cmd.data_group.add_command(archive_cmd.export, "export")
archive_cmd.data_group.add_command(archive_cmd.import_data, "import")
archive_cmd.data_group.add_command(archive_cmd.connect, "connect")
archive_cmd.data_group.add_command(archive_cmd.sync_command, "sync")
archive_cmd.data_group.add_command(archive_cmd.disconnect, "disconnect")
archive_cmd.data_group.add_command(report_cmd.report, "report")
cli.add_command(archive_cmd.data_group)

serve_cmd.serve_group.add_command(serve_cmd.start, "start")
serve_cmd.serve_group.add_command(serve_cmd.pair, "pair")
serve_cmd.serve_group.add_command(serve_cmd.devices, "devices")
serve_cmd.serve_group.add_command(serve_cmd.unpair, "unpair")
serve_cmd.serve_group.add_command(serve_cmd.install_agent, "install-agent")
serve_cmd.serve_group.add_command(serve_cmd.uninstall_agent, "uninstall-agent")
cli.add_command(serve_cmd.serve_group)
