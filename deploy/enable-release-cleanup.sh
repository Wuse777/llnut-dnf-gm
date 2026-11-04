#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Root required' >&2; exit 1; }
install -d -o root -g root -m 755 /var/lib/dnf-gm
exec 9>/var/lib/dnf-gm/maintenance.lock
chmod 600 /var/lib/dnf-gm/maintenance.lock
flock -x 9
BASE=$(readlink -f /opt/dnf-gm/current)
[[ "$BASE" == /opt/dnf-gm/releases/* && -f "$BASE/deploy/cleanup_worker.py" ]] || exit 1
# Explicit maintenance activation, separate from ordinary installs/upgrades.
install -d -m 755 /var/lib/dnf-gm/cleanup /run/dnf-gm /etc/systemd/system/dnf-gm.service.d
install -d -o root -g dnfgm -m 770 /var/lib/dnf-gm/cleanup/inbox
install -d -o root -g root -m 755 /var/lib/dnf-gm/cleanup/results
install -d -o root -g root -m 700 /var/lib/dnf-gm/cleanup/private
install -m 644 "$BASE/deploy/dnf-gm-cleanup.service" "$BASE/deploy/dnf-gm-cleanup.timer" /etc/systemd/system/
printf '[Service]\nReadWritePaths=/var/lib/dnf-gm/cleanup/inbox\n' > /etc/systemd/system/dnf-gm.service.d/cleanup.conf
# Operator must set cleanup_enabled=true in the private application config;
# this script deliberately does not modify config or restart an active GM.
systemctl daemon-reload
systemctl enable --now dnf-gm-cleanup.timer
printf '%s\n' 'Cleanup timer enabled. Set cleanup_enabled=true and restart only GM during the reviewed application deployment.'
