#!/usr/bin/env bash
#
# ./scripts/demo/record.sh [name ...] — re-record the demo GIFs in docs/demo/ with VHS
# (https://github.com/charmbracelet/vhs; `brew install vhs`), one scripts/demo/<name>.tape
# each, all with the same size, theme and window.
#
# find, prepare: the CLI GIFs. Each tape is played in a sandbox holding a copy of
# profile.example/ and an empty jobs/, through a `./door` that runs shim.py: the real
# CLI, with the job boards, scoring and tailoring stubbed (see shim.py). The two share the
# sandbox, in that order, so `prepare` sees `find`'s matches.
#
# claude: a Claude Code review session, from a fresh sandbox seeded with one run. The tape
# types `claude`, which plays claude_session.py: the real door MCP tools on the same
# stubs, drawn in Claude Code's style. No `claude` needed.
#
# app (not here): the desktop app's GIF, docs/demo/app.gif, is `npm run record:gif` in app/: the built app
# on its made-up demo data in a temp folder, driven by app/demo-record/app.record.ts, framed by app_gif.py.
#
# Nothing reads or writes your profile/ or jobs/ or syncs with your Google Drive (shim.py points
# the Drive state at the sandbox and turns the lock's sync hooks off), and no `claude` call is made.
# Default: find prepare claude.
#
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
demo="$repo/scripts/demo"
names=("$@")
[ ${#names[@]} -gt 0 ] || names=(find prepare claude)

command -v vhs >/dev/null || { echo "vhs is not installed: brew install vhs" >&2; exit 1; }

# A short, fixed path: the output prints it (prepare's PDF paths).
sandbox=/tmp/door-demo
trap 'rm -rf "$sandbox"' EXIT

make_sandbox() {
    rm -rf "$sandbox"
    mkdir -p "$sandbox/profile" "$sandbox/jobs"
    cp -R "$repo"/profile.example/. "$sandbox/profile/"
    # The example CV itself is refused: the demo scores a changed copy.
    printf '\n<!-- a demo copy -->\n' >> "$sandbox/profile/cv.md"
    # Both folders carry this build's data version, or the first command would upgrade (and back up) them.
    PYTHONPATH="$repo/src" poetry -C "$repo" run python -c '
import sys
from pathlib import Path
from door.core import migrations
root = Path(sys.argv[1])
migrations.write_version(root / "profile", migrations.current("profile"))
migrations.ensure_folder(root / "jobs", "jobs")
' "$sandbox"

    # The example profile, pointed at the sandbox (shim.py searches the demo's three fake boards only).
    poetry -C "$repo" run python - "$sandbox/profile" <<'EOF'
import json, sys
from pathlib import Path

profile = Path(sys.argv[1])
config = json.loads((profile / "config.json").read_text())
for key in ("cv_content",):
    config[key] = str(profile / Path(config[key]).name)
for key in ("hr_manager_aliases", "ashby_companies", "recruitee_companies", "career_sites"):
    config.pop(key, None)
config.pop("sites", None)
config["linkedin_discovery"] = False  # no network in the demo
config["follow_ai_fallback"] = False
(profile / "config.json").write_text(json.dumps(config, indent=2))
(profile / "companies.json").unlink()  # its example employers are real ones, read over the network
EOF

    cat > "$sandbox/door" <<EOF
#!/usr/bin/env bash
DOOR_DEMO_DIR="$sandbox" PYTHONPATH="$repo/src" exec poetry -C "$repo" run python "$demo/shim.py" "\$@"
EOF
    cat > "$sandbox/claude-demo" <<EOF
#!/usr/bin/env bash
DOOR_DEMO_DIR="$sandbox" PYTHONPATH="$repo/src" exec poetry -C "$repo" run python "$demo/claude_session.py" "\$@"
EOF
    chmod +x "$sandbox/door" "$sandbox/claude-demo"
}

mkdir -p "$repo/docs/demo"
fresh=1
for name in "${names[@]}"; do
    if [ "$fresh" = 1 ] || [ "$name" = claude ]; then
        make_sandbox
        fresh=0
    fi
    echo "recording $name"
    if [ "$name" = claude ]; then
        "$sandbox/claude-demo" --seed
        fresh=1
    fi
    (cd "$sandbox" && vhs "$demo/$name.tape")
    mv "$sandbox/$name.gif" "$repo/docs/demo/$name.gif"
done
