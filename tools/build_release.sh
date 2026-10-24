#!/usr/bin/env bash
set -euo pipefail
# Build on the maintenance computer, not the small game server.
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:?Usage: build_release.sh /absolute/new/release-directory}
[[ "$OUT" == /* && ! -e "$OUT" ]] || { echo 'New absolute output directory required' >&2; exit 1; }
PYTHON=${PYTHON_BIN:-python3.12}
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,12), "Build target is CPython 3.12"'
(cd "$ROOT/web"; npm ci; npm test; npm run build)
mkdir -p "$OUT/web"
cp -R "$ROOT/src" "$ROOT/deploy" "$ROOT/migrations" "$ROOT/licenses" "$ROOT/docs" "$OUT/"
cp "$ROOT/CHANGELOG.md" "$ROOT/SECURITY.md" "$ROOT/CONTRIBUTING.md" "$OUT/"
if git -C "$ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then git -C "$ROOT" describe --always --dirty > "$OUT/SOURCE_REVISION"; fi
cp "$ROOT/requirements.lock" "$ROOT/pyproject.toml" "$ROOT/README.md" "$ROOT/LICENSE" "$ROOT/THIRD_PARTY.md" "$OUT/"
cp -R "$ROOT/web/dist" "$OUT/web/"
find "$OUT" -name __pycache__ -type d -prune -exec rm -rf '{}' +
"$PYTHON" -m pip download --only-binary=:all: --dest "$OUT/wheels" -r "$ROOT/requirements.lock"
(cd "$OUT"; find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
printf 'Built release: %s\nTarget OS/architecture must match wheel platform. No game assets or credentials included.\n' "$OUT"
