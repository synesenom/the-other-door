#!/usr/bin/env bash
#
# Run the test suite via Poetry (the only supported dependency manager).
# One-time setup:  poetry install
#
#   ./scripts/run-test.sh            Offline suite (unit + fixture) under coverage,
#                            in parallel on every core (pytest-xdist; pass
#                            `-n 0` to run it serially), then regenerate the
#                            local coverage badge
#                            (docs/badges/coverage.svg; only when no arguments
#                            narrow the run). No network.
#
#   ./scripts/run-test.sh --live     Smoke tests against real sites (network). These
#                            are opt-in and excluded from the default run.
#                            Serial (they pace requests per host) and not run
#                            under coverage; the badge is left as-is.
#
#   ./scripts/run-test.sh --skills   The skills (/onboard, ...) run by the real model on
#                            the plan your `claude` is signed in to (no API key),
#                            against the app's test world: nothing leaves the
#                            computer. Run before a release (/dev-release does).
#                            Serial; several minutes and some plan usage each.
#
#   ./scripts/run-test.sh --app      The desktop app's tests, as CI runs them: type
#                            check, unit tests, the end-to-end smoke test, the
#                            core journeys and the phone app's test (app/, after
#                            `npm ci` there).
#
#   ./scripts/run-test.sh --release  Everything to pass before a release, one after
#                            the other, with a line each at the end: the offline
#                            suite, the app's tests with every journey, the skills,
#                            and the install test when DOOR_INSTALLER names an
#                            installer (docs/releasing.md). Not the live smoke
#                            tests: a site's bad day does not block a release.
#
# Extra arguments are passed through to pytest (not with --app or --release).
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--live" ]]; then
    shift
    set +e
    poetry run pytest -m live "$@"
    rc=$?
    set -e
    # Exit code 5 = no tests collected (no smoke tests defined yet).
    if [[ "$rc" -eq 5 ]]; then
        echo "No live (smoke) tests defined yet."
        exit 0
    fi
    exit "$rc"
fi

# The app's tests run on the Poetry interpreter, as in CI (app.yml).
app_tests() {   # $1: core | all — which journeys
    local journeys="test:journeys:core"
    [[ "${1:-core}" == "all" ]] && journeys="test:journeys"
    DOOR_PYTHON="$(poetry run which python)"
    export DOOR_PYTHON
    (cd app && npm run typecheck && npm test && npm run test:e2e && npm run "$journeys" && npm run test:web)
}

if [[ "${1:-}" == "--app" ]]; then
    app_tests core
    exit $?
fi

if [[ "${1:-}" == "--release" ]]; then
    results=()
    failed=0
    step() {   # $1: name, then the command
        local name="$1"; shift
        echo; echo "== $name"
        if "$@"; then results+=("PASS  $name"); else results+=("FAIL  $name"); failed=1; fi
    }
    set +e
    step "offline suite" poetry run pytest -n auto -q
    step "app (every journey)" app_tests all
    step "skills (real model)" poetry run pytest -m skills -n 0 -q -p no:cacheprovider tests/skills
    if [[ -n "${DOOR_INSTALLER:-}" ]]; then
        step "install test ($(basename "$DOOR_INSTALLER"))" bash -c "cd app && npm run test:install"
    else
        results+=("SKIP  install test (set DOOR_INSTALLER=<the downloaded installer>)")
    fi
    set -e
    echo; printf '%s\n' "${results[@]}"
    exit "$failed"
fi

if [[ "${1:-}" == "--skills" ]]; then
    shift
    exec poetry run pytest -m skills -n 0 -p no:cacheprovider tests/skills "$@"
fi

# Without the dev group, `poetry run pytest` falls through to a system pytest
# and dies with a misleading ModuleNotFoundError — say what to do instead.
if ! poetry run python -c "import pytest, responses, genbadge, xdist, pytest_cov" 2>/dev/null; then
    echo "Dev dependencies missing: run \`poetry install\` (it installs the dev group)." >&2
    exit 1
fi

# Default: offline suite under coverage, in parallel, then regenerate the badge.
# pytest-cov measures every xdist worker and combines their data into .coverage
# (`coverage run -m pytest -n auto` would measure only the controller); the
# report itself comes from coverage below. `--cov-report=` keeps pytest quiet.
# `|| true` tolerates pytest exit code 5 (no tests collected yet).
poetry run pytest -n auto --cov --cov-report= "$@" || true
poetry run coverage xml
poetry run coverage report

# Only the whole suite says what the coverage is: a run narrowed by arguments
# (one test file, -k, -m) leaves the badge as it is.
if [[ $# -gt 0 ]]; then
    echo "Arguments given: the coverage badge is left as it is (run with none to update it)."
    exit 0
fi

# genbadge has no __main__, so it is invoked via its console script.
poetry run genbadge coverage -i coverage.xml -o docs/badges/coverage.svg
