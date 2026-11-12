"""Door — job hunting pipeline.

Run via `./door <command>` (see `src/door/__main__.py`).

- `src/door/cli.py` — the Click group; every command is registered on it.
- `src/door/commands/<name>.py` — one module per command (or pair of commands): the
  `_<name>_core` function that does the work and returns a dict, and the Click
  command that renders it. `_common.py` holds what several commands share.
- `src/door/mcp_server.py` — the same cores as MCP tools.
- `src/door/core/workspace.py` — where `profile/` and `jobs/` live.
"""
