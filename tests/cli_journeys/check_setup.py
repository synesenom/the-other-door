"""CI: was setup fine, given that it ran with --no-claude --no-tex? (cli-journeys.yml)

setup ends 1 when it leaves a tool missing, and those two flags leave latex and the claude CLI missing on
purpose (the world's stand-ins take their place). Anything else missing, or an MCP server that does not
answer, is a real failure. Exits 1 then, naming it.
"""

import sys

from door.core import doctor, workspace

SKIPPED = {"latex", "claude CLI", "claude login", "profile"}

report = doctor.run_checks(workspace.PROFILE_DIR, workspace.JOBS_DIR)
bad = [f"{c['name']}: {c['status']}" for c in report["checks"]
       if c["status"] not in ("ok", "warn") and c["name"] not in SKIPPED]
mcp = doctor.probe_mcp_server(workspace.REPO_ROOT)
if mcp["status"] != "ok":
    bad.append(f"mcp server: {mcp.get('detail')}")
print("\n".join(bad) or "setup is fine")
sys.exit(1 if bad else 0)
