#!/usr/bin/env bash
#
# One-shot setup: Python 3.12 -> Poetry -> the Python packages, then `door doctor --fix`,
# which installs the rest (Tectonic, the claude CLI) and checks
# that the MCP server starts. Asks once up front; each step then shows a spinner and
# a checkmark. Safe to re-run: it is also the "repair my install" command.
#
#   ./scripts/setup.sh                 ask once, then install what is missing
#   ./scripts/setup.sh --yes           install without asking
#   ./scripts/setup.sh --no-tex --no-claude   (passed on; see `door setup --help`)
#
# Then open Claude Code here (`claude`) and say /onboard.
#
set -euo pipefail

cd "$(dirname "$0")/.."

FRAMES=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
# Colours on a terminal only: a yellow spinner, a green ✓, a red ✗.
if [[ -t 1 ]]; then YELLOW=$'\033[33m' GREEN=$'\033[32m' RED=$'\033[31m' RESET=$'\033[0m'; else YELLOW="" GREEN="" RED="" RESET=""; fi
CHECK="${GREEN}✓${RESET}" CROSS="${RED}✗${RESET}"

die() { echo "$*" >&2; exit 1; }

# step "Label" command...: run it with its output in a log, a spinner on a terminal,
# then a ✓ (or a ✗ with the log's tail, and stop).
step() {
    local label=$1 log rc=0 i=0 pid
    shift
    log=$(mktemp)
    if [[ -t 1 ]]; then
        "$@" >"$log" 2>&1 &
        pid=$!
        while kill -0 "$pid" 2>/dev/null; do
            printf '\r  %s %s' "${YELLOW}${FRAMES[i++ % 10]}${RESET}" "$label"
            sleep 0.1
        done
        wait "$pid" || rc=$?
        printf '\r\033[K'
    else
        "$@" >"$log" 2>&1 || rc=$?
    fi
    if [[ $rc -ne 0 ]]; then
        echo "  $CROSS $label"
        tail -n 20 "$log" | sed 's/^/      /' >&2
        rm -f "$log"
        die "$label failed — fix the above and re-run ./scripts/setup.sh"
    fi
    rm -f "$log"
    echo "  $CHECK $label"
}

done_step() { printf "  %s %-22salready installed\n" "$CHECK" "$1"; }

py_version() { "$1" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null; }

# A Python 3.12 on PATH. Nothing else is assumed: not Homebrew, not a system Python
# (macOS's Command Line Tools python3 is 3.9 and cannot even create the venv Poetry's
# installer needs), only curl.
PY312=""
for candidate in python3.12 python3 python; do
    command -v "$candidate" >/dev/null || continue
    version=$(py_version "$candidate") || continue
    [[ $version == 3.12.* ]] && { PY312=$(command -v "$candidate"); break; }
done

yes=0
for arg in "$@"; do [[ $arg == --yes ]] && yes=1; done

command -v curl >/dev/null || die "curl is needed to download Python and Poetry. Install it, then re-run ./scripts/setup.sh"

echo "door setup installs whatever of these is missing:"
echo "  Python 3.12, Poetry, the Python packages, Tectonic (LaTeX), the claude CLI"
if [[ $yes -eq 0 ]]; then
    printf "Continue? [Y/n] "
    read -r answer || answer=n
    [[ ${answer:-Y} =~ ^[Nn] ]] && die "Nothing installed."
fi
echo ""

export PATH="$HOME/.local/bin:$PATH"

# Python 3.12 before Poetry exists: Homebrew's when Homebrew is there, else a standalone
# build fetched by uv (one binary in ~/.local/bin, no sudo, no Python needed, on macOS
# and Linux alike).
no_python="Python 3.12 could not be installed. Install it from https://www.python.org/downloads/ (or your package manager), then re-run ./scripts/setup.sh"
install_python_brew() { brew install python@3.12 || { echo "$no_python"; return 1; }; }
install_python_uv() {
    command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
    command -v uv >/dev/null && uv python install 3.12 || { echo "$no_python"; return 1; }
}

if command -v poetry >/dev/null; then
    done_step "Poetry"
else
    if [[ -z $PY312 ]]; then
        if command -v brew >/dev/null; then
            step "Python 3.12" install_python_brew
            PY312="$(brew --prefix python@3.12)/bin/python3.12"
        else
            step "Python 3.12" install_python_uv
            PY312=$(uv python find 3.12) || die "$no_python"
        fi
        [[ -x $PY312 ]] || die "$no_python"
    fi
    step "Poetry" sh -c "curl -sSL https://install.python-poetry.org | '$PY312' -"
    command -v poetry >/dev/null || die "Poetry installed but not on PATH — add ~/.local/bin to PATH and re-run ./scripts/setup.sh"
fi

# poetry.lock is written by Poetry 2 and pyproject.toml uses the [project] table;
# Poetry 1.x misreads both and fails `poetry install` with a misleading lock error.
# `poetry python install` (a Python with no sudo, on any OS) arrived in 2.1.
poetry_version="$(poetry --version | sed -E 's/[^0-9]*([0-9][0-9.]*).*/\1/')"
major=${poetry_version%%.*}; minor=${poetry_version#*.}; minor=${minor%%.*}
upgrade="Upgrade it with \`poetry self update\` (or reinstall from https://python-poetry.org/docs/#installation), then re-run ./scripts/setup.sh"
[[ $major -lt 2 ]] && die "Poetry $poetry_version is too old: The other door needs Poetry 2 or later. $upgrade"

if [[ -n $PY312 ]]; then
    done_step "Python 3.12"
else
    [[ $major -eq 2 && $minor -lt 1 ]] && die "Poetry $poetry_version cannot install Python 3.12 (that needs Poetry 2.1+). $upgrade"
    step "Python 3.12" poetry python install 3.12
fi

step "Python packages" sh -c "poetry env use '${PY312:-3.12}' && poetry install"

# Tectonic, the claude CLI, the MCP server check: same list style.
args=("$@")
[[ $yes -eq 1 ]] || args=(--yes "${args[@]+"${args[@]}"}")
exec ./door doctor --fix "${args[@]}"
