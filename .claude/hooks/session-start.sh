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

# Open PRs of the user that need attention, one line each, so every session
# starts on them. Silent when gh is missing, signed out or offline (5 s cap).
if command -v gh >/dev/null 2>&1 && command -v perl >/dev/null 2>&1; then
  prs=$(perl -e 'alarm 5; exec @ARGV' gh pr list --author @me --state open \
    --json number,title,mergeable,statusCheckRollup,body --jq '
    .[] | "#\(.number)" as $n | (.statusCheckRollup // []) as $r
    | ([$r[] | select(.conclusion == "FAILURE" or .conclusion == "TIMED_OUT" or .conclusion == "CANCELLED" or .conclusion == "STARTUP_FAILURE" or .conclusion == "ACTION_REQUIRED")][0]) as $bad
    | ([$r[] | select(.context == "verify")][0].state) as $v
    | (if .mergeable == "CONFLICTING" then ["\($n) conflicts with main"] else [] end)
    + (if $bad then ["\($n): \($bad.name) failed"] else [] end)
    + (if ($r | length) == 0 then ["\($n): no checks ran"] else [] end)
    + (if $v == "FAILURE" or $v == "ERROR" then ["\($n): verify failed"] else [] end)
    + ((.body // "" | split("\n")
        | reduce .[] as $l ({f: false, r: []};
            if ($l | test("^\\s*(```|~~~)")) then .f = (.f | not)
            elif .f then .
            elif ($l | test("^\\s*([-*+]\\s+)?\\**Needs the maintainer:")) then
              .r += [$l | sub("^\\s*([-*+]\\s+)?\\**Needs the maintainer:\\**\\s*"; "")]
            else . end) | .r)
       | map("\($n): needs the maintainer: \(.)"))
    + (if $v == "SUCCESS" then ["\($n): verified, not merged"] else [] end)
    | .[]' 2>/dev/null) || prs=""
  if [ -n "$prs" ]; then
    echo "Open PRs that need you:"
    echo "$prs"
  fi
fi

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
