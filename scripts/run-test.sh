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
# Extra arguments are passed through to pytest.
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
