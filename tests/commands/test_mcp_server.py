"""Tests for the MCP server (issue #79, extended for #128 and #144).

Asserts every CLI command has a tool and every tool mirrors a command
(the parity test), the tools' parameter schemas, that each tool delegates
to its `_*_core` with the module-level `JOBS_DIR`/`PROFILE_DIR`, and that
expected failures come back as ``{"error": ...}``. Uses an in-process
client against the `FastMCP` instance; no subprocess, no network.
"""

import asyncio

import pytest
import json
from pathlib import Path

import mcp.shared.memory as mcp_client

from door.cli import cli
import door.mcp_server as server
from door.mcp_server import mcp as door_mcp, find_jobs as mcp_find_jobs
from door.commands import match as match_cmd
from door.commands import prepare as prepare_cmd
from door.commands import profile as profile_cmd
from door.commands import find as find_cmd
from door.commands import status as status_cmd
from door import i18n
from door.core import workspace
from paths import REPO_ROOT


def _list_tools():
    async def _run():
        async with mcp_client.create_connected_server_and_client_session(door_mcp) as client:
            return await client.list_tools()

    return asyncio.run(_run())


def _cli_command_names(group=None, prefix=""):
    """Every leaf Click command, sub-commands as "group sub" (e.g. "data export")."""
    import click

    group = group or cli
    names = set()
    for name, command in group.commands.items():
        full = f"{prefix}{name}"
        if isinstance(command, click.Group):
            names |= _cli_command_names(command, prefix=f"{full} ")
        else:
            names.add(full)
    return names


def test_every_cli_command_has_an_mcp_tool_and_vice_versa():
    """Parity (issue #144): the tool list equals the command list.

    A new Click command fails this test until it has a tool in
    `server.CLI_COMMAND_TOOLS`; a new tool fails it until it is mapped to
    the command it mirrors, or deliberately listed in
    `server.CONVERSATION_ONLY_TOOLS` (a tool only a conversation or an agent calls).
    """
    registered = {tool.name for tool in _list_tools().tools}
    mapped_tools = {tool for tools in server.CLI_COMMAND_TOOLS.values() for tool in tools}
    conversation_only = set(server.CONVERSATION_ONLY_TOOLS)

    assert set(server.CLI_COMMAND_TOOLS) | set(server.CLI_ONLY_COMMANDS) == _cli_command_names()
    assert not set(server.CLI_COMMAND_TOOLS) & set(server.CLI_ONLY_COMMANDS)
    assert not mapped_tools & conversation_only
    assert mapped_tools | conversation_only == registered


def test_mcp_server_find_jobs_tool_delegates_to_find_core(monkeypatch):
    captured = {}

    def fake_run_core(step, *, skip, boards, companies, dry_run, jobs_dir, profile_dir):
        captured.update({"step": step, "skip": skip, "boards": boards, "companies": companies, "dry_run": dry_run})
        return {
            "started_at": "t", "finished_at": "t", "elapsed_s": 0.0, "search": None,
            "match": None, "new_above_threshold": [], "top": [], "failures": [],
        }

    monkeypatch.setattr(find_cmd, "_find_core", fake_run_core)

    result = asyncio.run(mcp_find_jobs(step="search", boards=["jobindex"], company=["BEC"], dry_run=True))

    assert captured["step"] == "search"
    assert captured["boards"] == ["jobindex"] and captured["companies"] == ["BEC"] and captured["dry_run"] is True
    assert captured["skip"] == ()
    assert result["failures"] == []


def test_mcp_server_run_tool_takes_skip_and_no_step_for_a_full_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(find_cmd, "_find_core", lambda step=None, **kw: seen.update(kw, step=step) or {"failures": []})
    asyncio.run(mcp_find_jobs(skip=["discover"]))
    assert seen["step"] is None and seen["skip"] == ["discover"]


# --------------------------------------------------------------------------- #
# Parity tools (issue #144)
# --------------------------------------------------------------------------- #


def test_list_matches_tool_never_returns_descriptions(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    site_dir = jobs_dir / "postings" / "2026-07-01" / "jobindex"
    site_dir.mkdir(parents=True)
    (site_dir / "a.json").write_text(
        '{"id": "a", "title": "t", "company": "c", "location": "l", "description": "long", "score": 0.9}'
    )
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "no-profile")

    result = server.list_matches()

    assert [m["id"] for m in result["matches"]] == ["a"]
    from door.commands import _common as common

    assert result["min_score"] == common._DEFAULT_MIN_SCORE  # the conversation's default: the config's min_score
    assert all("description" not in m for m in result["matches"])


def test_show_tool_errors_come_back_as_error_dicts(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    assert server.show("../evil") == {"error": "invalid job_id: '../evil'"}
    assert server.show("missing") == {"error": "no posting found for job_id 'missing'"}


def test_existing_tools_also_return_error_dicts(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    assert server.compile("../evil") == {"error": "invalid job_id: '../evil'"}
    assert server.check_facts("../evil") == {"error": "invalid job_id: '../evil'"}
    assert "error" in server.set_status("job-a", "bogus")


def test_config_errors_come_back_as_error_dicts(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "config.json").write_text('{"min_sore": 1}')
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    result = asyncio.run(server.find_jobs())
    assert "min_sore" in result["error"]


def test_prepare_tool_delegates_with_minutes_converted(monkeypatch):
    captured = {}

    def fake(job_id, force=False, timeout_s=None, *, jobs_dir, profile_dir):
        captured.update(job_id=job_id, force=force, timeout_s=timeout_s, jobs_dir=jobs_dir, profile_dir=profile_dir)
        return {"job_id": job_id, "outcome": "prepared"}

    monkeypatch.setattr(prepare_cmd, "_prepare_core", fake)
    assert asyncio.run(server.prepare("job-a", force=True, timeout_min=2))["outcome"] == "prepared"
    assert captured == {
        "job_id": "job-a", "force": True, "timeout_s": 120,
        "jobs_dir": workspace.JOBS_DIR, "profile_dir": workspace.PROFILE_DIR,
    }


def test_init_profile_tool_passes_only_given_fields(monkeypatch):
    captured = {}

    def fake(fields, *, profile_dir, example_dir):
        captured.update(fields=fields, profile_dir=profile_dir, example_dir=example_dir)
        return {"config_path": "p", "copied": []}

    monkeypatch.setattr(profile_cmd, "_init_core", fake)
    server.init_profile(name="Ada", role_targets=["ML Lead"])
    assert captured["fields"] == {"name": "Ada", "role_targets": ["ML Lead"]}
    assert captured["profile_dir"] == workspace.PROFILE_DIR
    assert captured["example_dir"] == workspace.PROFILE_EXAMPLE_DIR


def test_init_profile_returns_the_disclaimer_of_a_source_turned_on(tmp_path, monkeypatch):
    from door.core.employers import discovery_sources

    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    result = server.init_profile(other={"linkedin_discovery": True})
    assert result["disclaimers"] == [{"key": "linkedin_discovery", "text": discovery_sources.info("linkedin")["disclaimer"]}]


def test_init_profile_tool_description_lists_the_supported_languages():
    """The model picks `languages` from the description, so it names every language with a file."""
    tool = next(t for t in _list_tools().tools if t.name == "init_profile")
    assert i18n.supported_language_names() in tool.description
    assert "{supported_languages}" not in tool.description


# --------------------------------------------------------------------------- #
# Long tools: async, off the event loop, streaming progress (issue #202)
# --------------------------------------------------------------------------- #

LONG_TOOLS = ("find_jobs", "prepare")


class _FakeCtx:
    """A stand-in for FastMCP's `Context`: records `report_progress` calls."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def report_progress(self, progress, total=None, message=None):
        if self.fail:
            raise RuntimeError("client went away")
        self.calls.append((progress, total, message))


def test_long_tools_are_async_and_ctx_is_not_in_the_schema():
    import inspect

    tools = {t.name: t for t in _list_tools().tools}
    for name in LONG_TOOLS:
        assert "ctx" not in tools[name].inputSchema.get("properties", {}), name
    for fn in (server.find_jobs, server.prepare):
        assert inspect.iscoroutinefunction(fn)


def test_tool_errors_wrapper_works_for_async_tools(monkeypatch):
    def boom(*a, **kw):
        raise ValueError("bad site")

    monkeypatch.setattr(find_cmd, "_find_core", boom)
    assert asyncio.run(server.find_jobs()) == {"error": "bad site"}


def test_long_tool_forwards_core_events_to_ctx_report_progress(monkeypatch):
    from door.core import progress
    from door.core.progress import Progress

    def fake_run_core(step=None, *, progress=None, **kw):
        with progress_mod.activate(progress):
            progress_mod.report("scraping (site 1/1)", site="jobindex", stage="scrape")
            progress_mod.report("detail", 2, 5, site="jobindex")
            progress_mod.report("jobindex: 3 posting(s)", 1, 1, site="jobindex", outcome="ok")
        return {"sites": []}

    progress_mod = progress
    monkeypatch.setattr(find_cmd, "_find_core", fake_run_core)
    ctx = _FakeCtx()
    assert asyncio.run(server.find_jobs(ctx=ctx)) == {"sites": []}

    assert [c[0] for c in ctx.calls] == [1.0, 2.0, 3.0]
    assert all(c[1] is None for c in ctx.calls)
    assert [c[2] for c in ctx.calls] == [
        Progress("scraping (site 1/1)", site="jobindex").line,
        Progress("detail", 2, 5, site="jobindex").line,
        "jobindex: 3 posting(s)",
    ]


def test_long_tool_without_ctx_does_not_pass_progress_kwarg(monkeypatch):
    seen = {}

    def strict(step=None, **kw):
        assert "progress" not in kw
        seen["called"] = True
        return {"sites": []}

    monkeypatch.setattr(find_cmd, "_find_core", strict)
    assert asyncio.run(server.find_jobs()) == {"sites": []}
    assert seen["called"]


def test_tool_writes_nothing_to_stdout(tmp_path, monkeypatch, capfd):
    import json

    import door.scrapers.boards.jobindex as ji
    from door.scrapers import record_error, report
    from profile_utils import write_config

    profile_dir = tmp_path / "profile"
    write_config(profile_dir, {"role_targets": ["x"], "location": "Copenhagen"})
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")

    def fake_scrape(config, **kw):
        report("'x': 0 results")
        record_error("jobindex", "an error")
        return []

    monkeypatch.setattr(ji, "scrape", fake_scrape)
    monkeypatch.delattr(ji, "iter_scrape", raising=False)
    from cli_utils import stub_match_result

    monkeypatch.setattr(match_cmd, "_match_core", lambda **kw: stub_match_result(tmp_path / "jobs"))

    ctx = _FakeCtx()
    result = asyncio.run(server.find_jobs(step="search", ctx=ctx))
    assert json.dumps(result)
    captured = capfd.readouterr()
    assert captured.out == "" and captured.err == ""
    assert any("'x': 0 results" in c[2] for c in ctx.calls)


def test_second_long_tool_is_refused_while_one_runs(monkeypatch):
    import threading

    release = threading.Event()
    started = threading.Event()

    def slow_run(*a, **kw):
        started.set()
        release.wait(5)
        return {"ok": True}

    monkeypatch.setattr(find_cmd, "_find_core", slow_run)
    monkeypatch.setattr(prepare_cmd, "_prepare_core", lambda *a, **kw: {"outcome": "no_matches"})

    async def scenario():
        first = asyncio.create_task(server.find_jobs())
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        second = await server.prepare()
        release.set()
        return await first, second

    first, second = asyncio.run(scenario())
    assert first == {"ok": True}
    assert "another long-running tool" in second["error"]
    assert asyncio.run(server.prepare()) == {"outcome": "no_matches"}


def test_status_summary_answers_while_find_jobs_is_running(tmp_path, monkeypatch):
    import threading

    from door.core import progress
    from door.core.lock import ledger_lock
    from profile_utils import write_config

    profile_dir = tmp_path / "profile"
    write_config(profile_dir, {"min_score": 0.6})
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs_dir)

    release = threading.Event()
    reported = threading.Event()

    def fake_run_core(*a, **kw):
        with ledger_lock(jobs_dir, "run"):
            progress.report("scraping (site 2/5)", site="jobindex", stage="scrape")
            reported.set()
            release.wait(5)
        return {"ok": True}

    monkeypatch.setattr(find_cmd, "_find_core", fake_run_core)

    async def scenario():
        task = asyncio.create_task(server.find_jobs())
        await asyncio.get_running_loop().run_in_executor(None, reported.wait, 5)
        summary = server.status_summary()  # the loop is free, so this answers at once
        release.set()
        await task
        return summary

    live = asyncio.run(scenario())["in_progress"]
    assert live["purpose"] == "run"
    assert live["message"] == "scraping (site 2/5)"
    assert live["site"] == "jobindex"


def test_progress_bridge_swallows_client_errors(monkeypatch):
    from door.core import progress

    def fake_run_core(step=None, *, progress=None, **kw):
        with progress_mod.activate(progress):
            progress_mod.report("one")
            progress_mod.report("two")
        return {"sites": ["done"]}

    progress_mod = progress
    monkeypatch.setattr(find_cmd, "_find_core", fake_run_core)
    assert asyncio.run(server.find_jobs(ctx=_FakeCtx(fail=True))) == {"sites": ["done"]}


def test_status_summary_tool_returns_in_progress_key(tmp_path, monkeypatch):
    from door.core import progress
    from door.core.lock import ledger_lock
    from profile_utils import write_config

    profile_dir = tmp_path / "profile"
    write_config(profile_dir, {"min_score": 0.6})
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")

    assert server.status_summary()["in_progress"] is None
    with ledger_lock(workspace.JOBS_DIR, "run"):
        progress.report("match", 1, 2, stage="run")
        live = server.status_summary()["in_progress"]
    assert set(live) == {"purpose", "pid", "started_at", "message", "done", "total", "site", "stage", "updated_at", "steps"}


def test_progress_notifications_reach_a_real_client_session(monkeypatch):
    """End to end through FastMCP's `Context` injection and the in-memory transport."""
    from door.core import progress

    def fake_run_core(step=None, *, progress=None, **kw):
        with progress_mod.activate(progress):
            progress_mod.report("scraping (site 1/1)", site="jobindex", stage="scrape")
            progress_mod.report("jobindex: 2 posting(s)", 1, 1, site="jobindex", stage="scrape", outcome="ok")
        return {"sites": []}

    progress_mod = progress
    monkeypatch.setattr(find_cmd, "_find_core", fake_run_core)
    received = []

    async def on_progress(value, total, message):
        received.append((value, total, message))

    async def scenario():
        async with mcp_client.create_connected_server_and_client_session(door_mcp) as client:
            return await client.call_tool("find_jobs", {}, progress_callback=on_progress)

    result = asyncio.run(scenario())
    assert not result.isError
    assert received == [(1.0, None, "jobindex: scraping (site 1/1)"), (2.0, None, "jobindex: 2 posting(s)")]


def test_tools_snapshot_matches_server():
    """The desktop app (app/) keeps the server's tool list in src/generated/tools.json:
    its allow-list for IPC and the record of every tool's parameters. A changed or new
    tool fails here until `npm run gen-tools` is run in app/ and the file committed."""
    snapshot = json.loads((REPO_ROOT / "app" / "src" / "generated" / "tools.json").read_text())
    live = sorted(
        ({"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema}
         for t in _list_tools().tools),
        key=lambda t: t["name"],
    )
    # Compare as parsed JSON: the wire form is what the app sees.
    live = json.loads(json.dumps(live))
    assert snapshot == live, "app/src/generated/tools.json is out of date: run `npm run gen-tools` in app/ and commit it"


# --------------------------------------------------------------------------- #
# Parameter parity: a tool takes what its command takes, and vice versa
# --------------------------------------------------------------------------- #

# Parameters that belong to one surface by design and are ignored on both
# sides: the CLI's rendering/exit-code switches, the tools' client context.
_SURFACE_ONLY = {"quiet", "ctx"}

# Where the two surfaces spell the same parameter differently, or one
# parameter on one side covers several on the other.
_ALIASES = {
    ("jobs add", "source"): {"path", "text"},  # a file argument, or pasted text
    ("doctor", "fix"): {"install", "fix_scrapers"},  # `--fix` is the `setup` tool
    ("doctor", "no_chromium"): {"install"},
    ("doctor", "no_claude"): {"install"},
    ("init", "show"): set(),  # `--show` is the no-argument `show_profile` tool
    ("cv stories add", "from_text"): set(),  # the shell drafts, asks for the gaps and confirms: the tool is `draft_stories` + `save_story`
}

# Tool parameters whose command asks for them instead of taking a flag: `init`'s
# wizard asks for the CV sources and the keywords to keep, which the `draft_cv`
# and `keywords` tools take as arguments (their `write`/`save` are the wizard's
# "use it?" answers, and the wizard always uses the default model).
_ASKED = {"init": {"sources", "write", "save", "model", "markdown"}}


def _cli_params(command_name: str) -> set[str]:

    if command_name.startswith("find "):
        # `find_jobs` is one tool for `find`'s five subcommands: a step takes the group's options (--skip, --days, ...) and
        # its own, and the tool takes them all, plus `step` to say which.
        return _cli_params_of(cli.commands["find"]) | _cli_params_of(cli.commands["find"].commands[command_name[5:]])
    group = cli
    *groups, leaf = command_name.split(" ")
    for name in groups:
        group = group.commands[name]
    return _cli_params_of(group.commands[leaf])


def _cli_params_of(command) -> set[str]:
    import click

    names = set()
    for param in command.params:
        if not isinstance(param, (click.Option, click.Argument)):
            continue
        names.add(param.name.rstrip("_"))
    return names


def test_the_find_jobs_tool_takes_every_option_of_every_step_and_the_group():
    """`find`'s subcommands each take a part of the tool's parameters; together with the group's, all of them
    (the tool's `step` is the subcommand itself)."""
    tool = {t.name: set(t.inputSchema["properties"]) for t in _list_tools().tools}["find_jobs"]
    steps = [name for name in server.CLI_COMMAND_TOOLS if name.startswith("find ")]
    assert len(steps) == 5
    cli_params = set().union(*(_cli_params(name) for name in steps)) - _SURFACE_ONLY
    assert cli_params == tool - {"step"} - _SURFACE_ONLY


def test_every_tool_takes_the_parameters_its_command_takes():
    """Option-level parity: whatever a command can be told, its tool can be told,
    and the other way round — modulo `_SURFACE_ONLY` and `_ALIASES` above.
    A new `--flag` fails this test until its tool takes it (and vice versa)."""
    tools = {tool.name: set(tool.inputSchema.get("properties", {})) for tool in _list_tools().tools}
    for command_name, tool_names in server.CLI_COMMAND_TOOLS.items():
        if command_name.startswith("find "):
            continue  # checked above: one tool, five subcommands
        tool_params = set().union(*(tools[name] for name in tool_names)) - _SURFACE_ONLY - _ASKED.get(command_name, set())
        cli_params = set()
        for param in _cli_params(command_name) - _SURFACE_ONLY:
            cli_params |= _ALIASES.get((command_name, param), {param})
        assert cli_params == tool_params, (
            f"{command_name!r}: CLI takes {sorted(cli_params)}, tool(s) {tool_names} take {sorted(tool_params)}"
        )


# --------------------------------------------------------------------------- Google Drive (#265)


def test_drive_tools_turn_failures_into_errors(monkeypatch):
    from door.core.sync import drive
    from door.core.lock import SyncConflict

    def conflict(*a, **k):
        raise SyncConflict("both changed: --keep-local or --keep-drive")

    def down(*a, **k):
        raise drive.DriveError("not configured in this build")

    monkeypatch.setattr(drive, "remote_meta", conflict)
    from door.commands import archive as archive_cmd

    monkeypatch.setattr(archive_cmd, "_sync_core", conflict)
    monkeypatch.setattr(archive_cmd, "_connect_core", down)
    assert "--keep-local" in server.sync_data()["error"]
    assert "not configured" in server.connect_drive()["error"]


def test_a_sync_conflict_says_so_in_a_field(monkeypatch):
    # The app offers "keep this computer" / "keep Drive" from the field, not from the wording.
    from door.commands import archive as archive_cmd
    from door.core.lock import SyncConflict

    def conflict(*a, **k):
        raise SyncConflict("both changed")

    monkeypatch.setattr(archive_cmd, "_sync_core", conflict)
    assert server.sync_data() == {"error": "both changed", "conflict": True}
    monkeypatch.setattr(archive_cmd, "_sync_core", lambda *a, **k: (_ for _ in ()).throw(ValueError("choose one")))
    assert server.sync_data() == {"error": "choose one"}


def test_status_summary_has_a_drive_block(tmp_path, monkeypatch):
    from door.core.sync import drive

    monkeypatch.setattr(drive, "CLIENT_ID", "id")
    monkeypatch.setattr(drive, "CLIENT_SECRET", "secret")

    summary = status_cmd._status_summary_core(jobs_dir=tmp_path / "jobs", profile_dir=tmp_path / "profile")
    assert summary["drive"] == {"connected": False, "account": None, "last_synced": None, "last_error": None, "configured": True}
    drive.write_state({"refresh_token": "rt", "account": "me@x.org", "last_synced": "2026-10-25T10:00:00+00:00", "last_error": "offline"})
    summary = status_cmd._status_summary_core(jobs_dir=tmp_path / "jobs", profile_dir=tmp_path / "profile")
    assert summary["drive"] == {
        "connected": True, "account": "me@x.org", "last_synced": "2026-10-25T10:00:00+00:00", "last_error": "offline",
        "configured": True,
    }
    assert "rt" not in json.dumps(summary)


def test_status_summary_says_when_this_build_has_no_drive(tmp_path, monkeypatch):
    from door.core.sync import drive

    monkeypatch.setattr(drive, "CLIENT_ID", "")
    summary = status_cmd._status_summary_core(jobs_dir=tmp_path / "jobs", profile_dir=tmp_path / "profile")
    assert summary["drive"]["configured"] is False


def test_startup_pull_is_best_effort(tmp_path, monkeypatch):
    from door.core.sync import drive
    from door.core.sync import sync

    calls = []
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(sync, "on_acquire", lambda purpose, jobs_dir: calls.append(purpose))
    server._startup_pull()  # not connected: nothing happens
    assert calls == []
    drive.write_state({"refresh_token": "rt"})
    server._startup_pull()
    assert calls == ["startup"]

    def boom(*a):
        raise RuntimeError("down")

    monkeypatch.setattr(sync, "on_acquire", boom)
    server._startup_pull()  # never raises


def test_startup_pull_skips_while_the_ledger_is_locked(tmp_path, monkeypatch):
    from door.core.sync import drive
    from door.core.sync import sync
    from door.core.lock import ledger_lock

    calls = []
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(sync, "on_acquire", lambda purpose, jobs_dir: calls.append(purpose))
    drive.write_state({"refresh_token": "rt"})
    with ledger_lock(tmp_path / "jobs", "run"):
        server._startup_pull()
    assert calls == []


def test_merge_companies_proposes_merges_and_reports_errors(tmp_path, monkeypatch):
    from door.core.employers import companies as store

    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    (tmp_path / "profile").mkdir()
    store.save(tmp_path / "profile", [
        store.Company(name="Tryg Forsikring A/S", status="unresolved", found_via="jobindex"),
        store.Company(name="Tryg Forsikring", status="unresolved", found_via="linkedin")])

    assert server.merge_companies()["candidates"] == [{"names": ["Tryg Forsikring A/S", "Tryg Forsikring"], "reason": "same name"}]
    assert server.merge_companies(["Tryg Forsikring A/S", "Tryg Forsikring"])["removed"] == "Tryg Forsikring"
    assert "error" in server.merge_companies(["Tryg Forsikring A/S", "Nobody"])
    assert "error" in server.merge_companies(["Tryg Forsikring A/S"])


@pytest.mark.parametrize("call, key", [
    (lambda: server.show_profile(), "options"),
    (lambda: server.suggest_titles(["Quant"]), "warning"),     # no CV yet
    (lambda: server.infer_basics("# CV"), "warning"),          # the model call failed
    (lambda: server.enrich(), "error"),                        # no profile
    (lambda: server.skill_gaps(), "error"),
])
def test_the_profile_tools_answer_with_their_cores_result_or_an_error(tmp_path, monkeypatch, call, key):
    from door.core import claude_cli

    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(workspace, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: (_ for _ in ()).throw(claude_cli.ClaudeError("no claude")))
    assert key in call()


def test_save_cv_is_a_conversation_only_tool_wrapping_the_core(tmp_path, monkeypatch):
    from door.core import workspace

    assert "save_cv" in server.CONVERSATION_ONLY_TOOLS
    assert "save_cv" in {tool.name for tool in _list_tools().tools}
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    assert "error" in server.save_cv("  ")
    assert not (tmp_path / "profile").exists()
    result = server.save_cv("# Me\n")
    assert (tmp_path / "profile" / "cv.md").read_text() == "# Me\n" and result["cv_path"].endswith("cv.md")


def test_photo_tools_are_conversation_only_writing_tools_wrapping_the_cores(tmp_path, monkeypatch):
    from PIL import Image

    from door.core import workspace

    for tool in ("save_photo", "remove_photo"):
        assert tool in server.CONVERSATION_ONLY_TOOLS and tool in server.WRITING_TOOLS
        assert tool in {t.name for t in _list_tools().tools}
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", workspace.REPO_ROOT / "profile.example")
    Image.new("RGB", (800, 1000), "tan").save(tmp_path / "me.jpg", "JPEG")
    result = server.save_photo(str(tmp_path / "me.jpg"))
    assert result["photo_path"] == str(tmp_path / "profile" / "photo.jpg")
    assert server.remove_photo() == {"removed": True}


def test_save_photo_refuses_a_path_outside_the_data_folder(tmp_path, monkeypatch):
    from door.core import workspace

    monkeypatch.setattr(workspace, "HOME", tmp_path / "home")
    (tmp_path / "home").mkdir()
    outside = tmp_path / "elsewhere.jpg"
    outside.write_bytes(b"x")
    assert "outside the data folder" in server.save_photo(str(outside))["error"]


def test_init_profile_keeps_the_photo_key_inside_the_data_folder(tmp_path, monkeypatch):
    from door.core import workspace

    monkeypatch.setattr(workspace, "HOME", tmp_path / "home")
    (tmp_path / "home").mkdir()
    assert "outside the data folder" in server.init_profile(other={"photo": str(tmp_path / "x.jpg")})["error"]


def test_story_tools_wrap_the_cores_and_turn_expected_errors_into_error(tmp_path, monkeypatch):
    from door.core import workspace

    for tool in ("list_stories", "draft_stories"):
        assert tool in server.READ_ONLY_TOOLS and tool in {t.name for t in _list_tools().tools}
    for tool in ("save_story", "remove_story"):
        assert tool in server.WRITING_TOOLS and tool in {t.name for t in _list_tools().tools}
    monkeypatch.setattr(workspace, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", workspace.REPO_ROOT / "profile.example")
    assert server.list_stories()["stories"] == []
    assert "error" in server.save_story("T", "", "a", "r", "x")
    saved = server.save_story("T", "c", "a", "r", "x")
    assert saved["outcome"] == "added"
    assert "skills" not in server.list_stories()["stories"][0]
    assert "error" in server.remove_story("nope")
    assert server.remove_story("T")["outcome"] == "removed"
    assert "error" in server.draft_stories()


def test_main_loads_the_language_libraries_before_serving(monkeypatch):
    # #18: before the event loop and its worker threads exist (numpy's OpenBLAS hung loading on a worker on Windows)
    order = []
    monkeypatch.setattr(server.problem_log, "setup", lambda: None)
    monkeypatch.setattr(server, "_startup_pull", lambda: order.append("pull"))
    monkeypatch.setattr(server.i18n, "preload_language_detection", lambda: order.append("preload"))
    monkeypatch.setattr(server.mcp, "run", lambda **kw: order.append("serve"))
    server.main()
    assert order.index("preload") < order.index("serve")


# --------------------------------------------------------------------------- each tool's argument reaches its core


def _posting_on_disk(jobs_dir, job_id="jobindex-top"):
    site_dir = jobs_dir / "postings" / "2026-07-01" / "jobindex"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / f"{job_id}.json").write_text(json.dumps({
        "id": job_id, "title": "Data scientist", "company": "Acme", "location": "Copenhagen",
        "url": f"https://example.com/{job_id}", "description": "We need a data scientist who ships. " * 20,
        "source": "jobindex", "score": 0.9,
    }))


def test_set_status_records_the_event_on_the_date_given(cli_env):
    _posting_on_disk(cli_env.jobs_dir)

    result = server.set_status("jobindex-top", "applied", at="2026-06-20")

    assert result["at"] == "2026-06-20T00:00:00+00:00"
    ledger = json.loads((cli_env.jobs_dir / "applications.json").read_text())
    assert [e["at"] for e in ledger["jobindex-top"]["history"]] == ["2026-06-20T00:00:00+00:00"]


def test_show_with_open_opens_both_prepared_pdfs(cli_env, monkeypatch):
    from door.commands import matches as matches_cmd
    import door.render.pdf_render as pdf_render

    _posting_on_disk(cli_env.jobs_dir)
    out = cli_env.jobs_dir / "output" / "jobindex-top"
    out.mkdir(parents=True)
    for name in ("cv.pdf", "cover_letter.pdf"):
        (out / name).write_bytes(b"%PDF")
    for name in ("cv_page_1.png", "cover_letter_page_1.png"):
        (out / name).write_bytes(b"png")
    monkeypatch.setattr(pdf_render, "get_page_count", lambda path: 1)
    opened = []
    monkeypatch.setattr(matches_cmd, "_open_files", lambda paths: opened.extend(paths))

    server.show("jobindex-top")
    assert opened == []
    server.show("jobindex-top", open=True)
    assert opened == [str(out / "cv.pdf"), str(out / "cover_letter.pdf")]


def test_setup_runs_the_scraper_fix_it_is_given(cli_env, monkeypatch):
    import door.core.doctor as doctor
    from door.core import scraper_fix

    checks = [
        {"name": "claude CLI", "status": "ok", "required": True, "detail": "", "fix": None},
        {"name": "scraper: jobindex", "status": "drift", "required": False, "detail": "no results block",
         "fix": "choose `fix scraper` in `setup`", "fixable": True},
    ]
    monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: {"ok": True, "checks": checks, "last_run": None, "last_scrape": []})
    fixed = []
    monkeypatch.setattr(scraper_fix, "fix_scraper", lambda site, **kw: fixed.append(site) or {"site": site, "outcome": "pr", "url": "u"})

    server.setup(install=[], yes=True)
    assert fixed == []
    result = server.setup(install=[], yes=True, fix_scrapers=["jobindex"])
    assert fixed == ["jobindex"]
    assert result["fixes"] == [{"site": "jobindex", "outcome": "pr", "url": "u"}]


class _Drive:
    """Google Drive's one archive: a blob and its version (as `tests/core/test_sync_unit.py`'s FakeDrive)."""

    def __init__(self, monkeypatch, tmp_path):
        from door.core.sync import drive

        monkeypatch.setattr(drive, "_BASE", tmp_path / "cfg")
        drive.write_state({"refresh_token": "rt", "account": "me@x.org"})
        self.blob, self.version, self.properties, self.uploads = None, 0, {}, 0
        monkeypatch.setattr(drive, "remote_meta", lambda: None if self.blob is None else {
            "id": "A", "version": str(self.version), "properties": dict(self.properties)})
        monkeypatch.setattr(drive, "download", lambda dest: Path(dest).write_bytes(self.blob))
        monkeypatch.setattr(drive, "upload", self.upload)

    def upload(self, src, properties=None):
        self.properties = dict(properties or {})
        self.blob = Path(src).read_bytes()
        self.version += 1
        self.uploads += 1
        return str(self.version)


@pytest.mark.parametrize("keep, action, mine_kept", [("keep_local", "push", True), ("keep_drive", "pull", False)])
def test_sync_data_settles_a_both_sides_change_the_way_asked(tmp_path, monkeypatch, keep, action, mine_kept):
    profile, jobs = tmp_path / "profile", tmp_path / "jobs"
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "JOBS_DIR", jobs)
    monkeypatch.setattr(workspace, "BACKUPS_DIR", tmp_path / "backups")
    fake = _Drive(monkeypatch, tmp_path)
    profile.mkdir()
    (profile / "config.json").write_text("{}")
    (profile / ".data_version").write_text("0.1")
    jobs.mkdir()
    (jobs / "history.json").write_text("{}")
    assert server.sync_data()["action"] == "push"
    fake.version += 1  # another computer pushed
    (jobs / "mine.json").write_text("mine")
    assert server.sync_data()["conflict"] is True

    assert server.sync_data(**{keep: True})["action"] == action
    assert (jobs / "mine.json").exists() is mine_kept
