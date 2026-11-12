#!/usr/bin/env bash
# Checks app/resources/ (bundle-python.sh's output) on its own, without Electron (#223), with an empty
# user home and a minimal PATH, as a just-installed app would run it:
#   the bundled Python imports door and its native packages; the MCP server answers `initialize`;
#   doctor finds the bundled Tectonic and has no developer checks; Tectonic compiles a page.
# --offline skips the compile (Tectonic downloads its LaTeX packages on first use).
set -euo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
RES="${1:-$APP/resources}"
[ "${1:-}" = "--offline" ] && RES="$APP/resources"
OFFLINE=0; for a in "$@"; do [ "$a" = "--offline" ] && OFFLINE=1; done
PY="$RES/python/bin/python3"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/user" "$TMP/data"
export HOME="$TMP/user" DOOR_HOME="$TMP/data" DOOR_BIN="$RES/bin" PYTHONPATH="$RES/door/src" \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PATH="$RES/bin:/usr/bin:/bin"
cd "$RES/door"
ok() { echo "ok  $1"; }

"$PY" -s -c "import door.mcp_server, pypdfium2, quickjs, py3langid, pydantic, cryptography, dns.resolver" && ok "imports"

INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check-bundle","version":"0"}}}'
reply="$(printf '%s\n' "$INIT" | "$PY" -s -m door.mcp_server 2>/dev/null | head -1)"
case "$reply" in *'"result"'*) ok "mcp server answers initialize" ;; *) echo "FAIL mcp server: $reply" >&2; exit 1 ;; esac

"$PY" -s - <<'PY'
import os
from door.commands import setup
from door.core import workspace
report = setup._doctor_core(profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR, probe=False)
by = {c["name"]: c for c in report["checks"]}
assert by["latex"]["status"] == "ok" and os.environ["DOOR_BIN"] in by["latex"]["detail"], by["latex"]
assert "dev dependencies" not in by, "a packaged app has no developer checks"
assert not workspace.is_checkout()
print("ok  doctor: Tectonic from the bundle, no developer checks")
PY

if [ "$OFFLINE" = 0 ]; then
  printf '\\documentclass{article}\\begin{document}door\\end{document}\n' > "$TMP/page.tex"
  "$RES/bin/tectonic" -X compile --outdir "$TMP" "$TMP/page.tex" >/dev/null 2>&1
  [ -s "$TMP/page.pdf" ] && ok "tectonic compiles a page"
fi
# nothing was written inside the bundle
if find "$RES" -newer "$TMP/data" -not -path "*/__pycache__*" | grep -q .; then
  echo "FAIL something was written inside $RES:" >&2; find "$RES" -newer "$TMP/data" | head >&2; exit 1
fi
ok "nothing written inside the bundle"
