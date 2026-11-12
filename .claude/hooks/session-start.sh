#!/bin/bash
# SessionStart hook for Claude Code cloud sessions.
#
# A cloud session starts from a fresh clone with no `.venv/`, and `.mcp.json`
# starts The other door's MCP server with `.venv/bin/python`, so without this every
# door tool is "failed to connect" and nothing in docs/manual-claude.md works.
# Installs the Python dependencies with Poetry, once per poetry.lock: a stamp
# in .venv/ skips the install on a container that already has it. Local
# sessions are left alone: ./scripts/setup.sh is the install there.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

stamp=.venv/.door-lock-sha
want=$(sha256sum poetry.lock | cut -d' ' -f1)
if [ -x .venv/bin/python ] && [ "$(cat "$stamp" 2>/dev/null)" = "$want" ]; then
  exit 0
fi

if ! command -v poetry >/dev/null 2>&1; then
  echo "session-start: poetry not found; run ./scripts/setup.sh" >&2
  exit 0
fi

# The project pins Python >=3.12,<3.13; pick that interpreter when the image
# has several and no virtualenv exists yet.
if [ ! -x .venv/bin/python ] && command -v python3.12 >/dev/null 2>&1; then
  poetry env use python3.12 >/dev/null 2>&1 || true
fi

poetry install --no-interaction --no-ansi 2>&1 | tail -n 3
echo "$want" > "$stamp"
echo "session-start: door dependencies installed ($(.venv/bin/python --version))"
