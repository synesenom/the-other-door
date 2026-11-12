#!/usr/bin/env bash
# Builds what a packaged app carries (#223) for this computer's system and processor, into app/resources/:
#   python/   python-build-standalone 3.12 with The other door's locked packages installed into it (by hash, wheels only)
#   door/   src/, .claude/agents/{tailor,reviewer,matcher}.md and profile.example/, as in a checkout
#   bin/      Tectonic
# Pinned in scripts/bundle.lock.json; downloads are cached in app/.bundle-cache/ (DOOR_BUNDLE_CACHE).
# No cross-building: run it on each system. Windows: bundle-python.ps1 (#355). Then: scripts/check-bundle.sh.
set -euo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$APP/.." && pwd)"
OUT="$APP/resources"
CACHE="${DOOR_BUNDLE_CACHE:-$APP/.bundle-cache}"
LOCK="$APP/scripts/bundle.lock.json"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PY_TRIPLE=aarch64-apple-darwin; TT_TRIPLE=aarch64-apple-darwin ;;
  Darwin-x86_64) PY_TRIPLE=x86_64-apple-darwin; TT_TRIPLE=x86_64-apple-darwin ;;
  Linux-x86_64) PY_TRIPLE=x86_64-unknown-linux-gnu; TT_TRIPLE=x86_64-unknown-linux-musl ;;
  *) echo "bundle-python.sh: $(uname -s) $(uname -m) is not supported (x64 Linux, macOS)" >&2; exit 2 ;;
esac

field() { node -e "const l=require(process.argv[1]);const v=process.argv[2].split('.').reduce((o,k)=>o[k],l);process.stdout.write(String(v))" "$LOCK" "$1"; }
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

# fetch URL SHA256: sets FETCHED to the cached file, downloaded once and checked every time
fetch() {
  local url="$1"
  local want="$2"
  local file="$CACHE/$(basename "${url//%40/@}")"
  mkdir -p "$CACHE"
  if [ ! -f "$file" ] || [ "$(sha256 "$file")" != "$want" ]; then
    echo "downloading $(basename "$file")" >&2
    curl -fsSL --retry 3 -o "$file.part" "$url"
    mv "$file.part" "$file"
  fi
  local got
  got="$(sha256 "$file")"
  [ "$got" = "$want" ] || { echo "checksum mismatch for $file: $got, wanted $want" >&2; exit 1; }
  FETCHED="$file"
}

rm -rf "$OUT"
mkdir -p "$OUT/bin" "$OUT/door/.claude/agents"

# 1. the Python runtime
PY_VERSION="$(field python.version)"; PY_TAG="$(field python.tag)"
py_url="$(field python.url)"; py_url="${py_url//\{tag\}/$PY_TAG}"; py_url="${py_url//\{version\}/$PY_VERSION}"; py_url="${py_url//\{triple\}/$PY_TRIPLE}"
fetch "$py_url" "$(field "python.sha256.$PY_TRIPLE")"
tar -xzf "$FETCHED" -C "$OUT"   # → $OUT/python
PY="$OUT/python/bin/python3"

# 2. The other door's packages, from poetry.lock (main group), by hash, wheels only: a package with no wheel for
#    this system fails the build here rather than on a user's computer
"$PY" "$APP/scripts/lock_requirements.py" "$REPO/poetry.lock" > "$CACHE/requirements.txt"
PIP_CACHE_DIR="$CACHE/pip" "$PY" -s -m pip install --quiet --disable-pip-version-check --no-deps --require-hashes \
  --only-binary=:all: --no-compile -r "$CACHE/requirements.txt"

# 3. The other door itself, laid out as in a checkout (REPO_ROOT = door/)
rsync -a --exclude '__pycache__' "$REPO/src/" "$OUT/door/src/"
cp "$REPO/.claude/agents/tailor.md" "$REPO/.claude/agents/reviewer.md" "$REPO/.claude/agents/matcher.md" "$OUT/door/.claude/agents/"
rsync -a "$REPO/profile.example/" "$OUT/door/profile.example/"

# 4. Tectonic
TT_VERSION="$(field tectonic.version)"
tt_url="$(field tectonic.url)"; tt_url="${tt_url//\{version\}/$TT_VERSION}"; tt_url="${tt_url//\{triple\}/$TT_TRIPLE}"; tt_url="${tt_url//\{ext\}/tar.gz}"
fetch "$tt_url" "$(field "tectonic.sha256.$TT_TRIPLE")"
tar -xzf "$FETCHED" -C "$OUT/bin"
chmod +x "$OUT/bin/tectonic"

# 5. trim what a server never runs, then compile once (the app runs with PYTHONDONTWRITEBYTECODE)
STDLIB="$OUT/python/lib/python${PY_VERSION%.*}"
rm -rf "$STDLIB/test" "$STDLIB/idlelib" "$STDLIB/tkinter" "$STDLIB/turtledemo" "$STDLIB/ensurepip" \
  "$OUT/python/lib/tcl"* "$OUT/python/lib/tk"* "$OUT/python/lib/itcl"* "$OUT/python/lib/thread"* 2>/dev/null || true
find "$STDLIB/site-packages" -type d \( -name tests -o -name test \) -prune -exec rm -rf {} + 2>/dev/null || true
"$PY" -s -m compileall -q -j 0 "$STDLIB" "$OUT/door/src" >/dev/null || true
# pip only installed the packages; the app never runs it
rm -rf "$STDLIB/site-packages/pip" "$STDLIB/site-packages"/pip-*.dist-info "$OUT/python/bin/pip"*

echo "bundled for $PY_TRIPLE into $OUT ($(du -sh "$OUT" | cut -f1))"
