#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 && -L /opt/dnf-gm/previous ]] || { echo 'Root and previous release required' >&2; exit 1; }
PREVIOUS=$(readlink -f /opt/dnf-gm/previous)
[[ "$PREVIOUS" == /opt/dnf-gm/releases/* && -f "$PREVIOUS/deploy/install.sh" ]] || exit 1
# Reinstalls the previous release's locked wheels and service units, preserves DB.
# Nginx snippets must be removed/reloaded manually before rollback if desired.
exec bash "$PREVIOUS/deploy/install.sh"
