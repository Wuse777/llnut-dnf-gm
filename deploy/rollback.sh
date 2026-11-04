#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 && -L /opt/dnf-gm/previous ]] || { echo 'Root and previous release required' >&2; exit 1; }
# Keep the same inherited flock when rollback execs an installer.
install -d -m 755 /var/lib/dnf-gm
if [[ "$(readlink /proc/$$/fd/9 || true)" != /var/lib/dnf-gm/maintenance.lock ]]; then
 exec 9>/var/lib/dnf-gm/maintenance.lock
fi
chmod 600 /var/lib/dnf-gm/maintenance.lock
flock -x 9

# Older installers do not know the cleanup protocol. Disable it across reboot.
if [[ -f /etc/systemd/system/dnf-gm-cleanup.timer ]]; then systemctl disable --now dnf-gm-cleanup.timer; fi
PREVIOUS=$(readlink -f /opt/dnf-gm/previous)
[[ "$PREVIOUS" == /opt/dnf-gm/releases/* && -f "$PREVIOUS/deploy/install.sh" ]] || exit 1
# Reinstalls the previous release's locked wheels and service units, preserves DB.
# Nginx snippets must be removed/reloaded manually before rollback if desired.
exec bash "$PREVIOUS/deploy/install.sh"
