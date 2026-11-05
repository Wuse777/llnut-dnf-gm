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

PREVIOUS=$(readlink -f /opt/dnf-gm/previous)
[[ "$PREVIOUS" == /opt/dnf-gm/releases/* && -f "$PREVIOUS/deploy/install.sh" ]] || exit 1
BASE=$(cd "$(dirname "$0")/.." && pwd)
# Preserve the running version and monitor while any game maintenance is active.
/opt/dnf-gm/venv/bin/python "$BASE/deploy/check_maintenance_idle.py"
# Quiesce the only GM writer before checking stored request compatibility. The
# monitor cannot auto-start it during a failed or interrupted rollback.
INHIBIT_OWNED=false
if [[ ! -e /var/lib/dnf-gm/no-auto-recover ]]; then
 touch /var/lib/dnf-gm/no-auto-recover
 INHIBIT_OWNED=true
fi
for UNIT in dnf-gm-monitor.service dnf-gm.service; do
 if systemctl cat "$UNIT" >/dev/null 2>&1; then systemctl stop "$UNIT"; fi
done
/opt/dnf-gm/venv/bin/python "$BASE/deploy/check_rollback.py" "$PREVIOUS" || {
 echo 'GM remains stopped; current release and data preserved. Review compatibility before manually enabling it.' >&2
 exit 1
}

# Older installers do not know the cleanup protocol. Disable it across reboot.
if [[ -f /etc/systemd/system/dnf-gm-cleanup.timer ]]; then systemctl disable --now dnf-gm-cleanup.timer; fi
# Reinstalls the previous release's locked wheels and service units, preserves DB.
# Nginx snippets must be removed/reloaded manually before rollback if desired.
bash "$PREVIOUS/deploy/install.sh"
# Remove only the inhibit we created, and only after the installer succeeded.
if [[ "$INHIBIT_OWNED" == true ]]; then rm -f /var/lib/dnf-gm/no-auto-recover; fi
