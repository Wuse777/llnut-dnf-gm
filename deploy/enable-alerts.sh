#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Root required' >&2; exit 1; }
BASE=$(readlink -f /opt/dnf-gm/current)
[[ "$BASE" == /opt/dnf-gm/releases/* && -f "$BASE/deploy/alert_worker.py" ]] || exit 1
[[ -f /etc/dnf-gm-alerts.json && ! -L /etc/dnf-gm-alerts.json ]] || { echo 'Prepare the private alerts.json first' >&2; exit 1; }
# No game credentials, DB grant, web write permission or core service restart.
getent passwd dnfgm-alert >/dev/null || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin dnfgm-alert
install -d -o dnfgm-alert -g dnfgm-alert -m 755 /var/lib/dnf-gm/alerts
chown root:dnfgm-alert /etc/dnf-gm-alerts.json
chmod 640 /etc/dnf-gm-alerts.json
PYTHONPATH="$BASE/src:$BASE/deploy" /opt/dnf-gm/venv/bin/python - <<'PY'
from alert_worker import private_config
private_config()
PY
install -m 644 "$BASE/deploy/dnf-gm-alert.service" "$BASE/deploy/dnf-gm-alert.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dnf-gm-alert.timer
printf '%s\n' 'Independent alert timer enabled. No GM/game/core service restart. Empty webhook means local history only.'
