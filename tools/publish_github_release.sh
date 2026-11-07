#!/usr/bin/env bash
# Source + static web publication only. Never reads deployment credentials.
set -euo pipefail
TAG=${1:?Usage: publish_github_release.sh vMAJOR.MINOR.PATCH}
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'A fixed semantic version tag is required' >&2; exit 1; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
VERSION=${TAG#v}
: "${GITHUB_REPOSITORY:?Set the GitHub owner/repository}"
REVISION=$(git rev-parse HEAD)
[[ "$(git rev-parse "refs/tags/$TAG^{commit}")" == "$REVISION" ]] || { echo 'Checkout must match the exact release tag' >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo 'A clean checkout is required' >&2; exit 1; }
python3 tools/check_documentation.py
python3 - "$VERSION" <<'PY'
import json,sys,tomllib
from pathlib import Path
v=sys.argv[1]
assert tomllib.loads(Path('pyproject.toml').read_text())['project']['version']==v
assert json.loads(Path('web/package.json').read_text())['version']==v
assert Path(f'docs/releases/v{v}.md').is_file()
PY
if gh release view "$TAG" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  echo 'Release already exists. Inspect it; never overwrite an existing publication automatically.' >&2
  exit 1
fi
npm --prefix web ci
npm --prefix web run build
[[ -z "$(git status --porcelain)" ]] || { echo 'Build modified tracked files' >&2; exit 1; }
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
SOURCE="llnut-dnf-gm-$VERSION-source.tar.gz"
WEB="llnut-dnf-gm-$VERSION-web.tar.gz"
git archive --format=tar --prefix="llnut-dnf-gm-$VERSION/" "$REVISION" | gzip -n > "$OUT/$SOURCE"
mkdir -p "$OUT/static/web"
cp -R web/dist "$OUT/static/web/"
printf '%s\n' "$REVISION" > "$OUT/static/SOURCE_REVISION"
tar -C "$OUT/static" -czf "$OUT/$WEB" web/dist SOURCE_REVISION
(cd "$OUT"; sha256sum "$SOURCE" "$WEB" > SHA256SUMS; sha256sum -c SHA256SUMS)
# A draft prevents publishing a release whose attachments are only half uploaded.
# A failed job may leave that draft for manual reconciliation; reruns refuse it.
gh release create "$TAG" --repo "$GITHUB_REPOSITORY" --verify-tag --target "$REVISION" \
  --draft --title "$TAG · 中文 GM 工作台与文档焕新" --notes-file "docs/releases/$TAG.md"
gh release upload "$TAG" --repo "$GITHUB_REPOSITORY" "$OUT/$SOURCE" "$OUT/$WEB" "$OUT/SHA256SUMS"
gh release edit "$TAG" --repo "$GITHUB_REPOSITORY" --draft=false --latest
printf 'Published %s from %s. No server deployment performed.\n' "$TAG" "$REVISION"
