#!/usr/bin/env bash
set -euo pipefail
# Install ONLY the GM application. Never touches Nginx, Docker or game services.
[[ $EUID == 0 ]] || { echo 'Root required' >&2; exit 1; }
# Keep the same inherited flock when rollback execs an installer.
install -d -m 755 /var/lib/dnf-gm
if [[ "$(readlink /proc/$$/fd/9 || true)" != /var/lib/dnf-gm/maintenance.lock ]]; then
 exec 9>/var/lib/dnf-gm/maintenance.lock
fi
chmod 600 /var/lib/dnf-gm/maintenance.lock
flock -x 9

BASE=$(cd "$(dirname "$0")/.." && pwd)
[[ "$BASE" == /opt/dnf-gm/releases/* && -f "$BASE/web/dist/index.html" ]] || { echo 'Expected built versioned release' >&2; exit 1; }
[[ -f /etc/dnf-gm/config.json && -f /etc/dnf-gm/monitor.json ]] || { echo 'Provision config and review monitor.json first' >&2; exit 1; }
[[ -f "$BASE/SHA256SUMS" ]] || { echo 'Missing release checksums' >&2; exit 1; }
(cd "$BASE" && sha256sum --check --strict SHA256SUMS >/dev/null)
# A prior executor may have exited while a game drain still owns maintenance.
# Refuse before stopping GM/monitor or replacing the interpreter/current release.
PYTHON=${PYTHON_BIN:-python3.12}
"$PYTHON" "$BASE/deploy/check_maintenance_idle.py"
getent passwd dnfgm >/dev/null
# Published code must not be mutable by the web application.
chown -hR root:root "$BASE"
chmod -R go-w "$BASE"
install -d -m 755 /var/lib/dnf-gm
CLEANUP_RESTART=false
if systemctl is-active --quiet dnf-gm-cleanup.timer; then
 systemctl stop dnf-gm-cleanup.timer
 CLEANUP_RESTART=true
fi
RECOVERY_INHIBIT_OWNED=false
if [[ ! -e /var/lib/dnf-gm/no-auto-recover ]]; then
 touch /var/lib/dnf-gm/no-auto-recover
 RECOVERY_INHIBIT_OWNED=true
fi
for UNIT in dnf-gm-monitor.service dnf-gm.service; do
 if systemctl cat "$UNIT" >/dev/null 2>&1; then systemctl stop "$UNIT"; fi
done
"$PYTHON" -m venv /opt/dnf-gm/venv
/opt/dnf-gm/venv/bin/python -m pip install --no-index --find-links "$BASE/wheels" -r "$BASE/requirements.lock"
# Allow only the configured DB IPv4 to the sandbox; do not open all private networks.
DB_IP=$(PYTHONPATH="$BASE/src" /opt/dnf-gm/venv/bin/python - <<'PY'
import ipaddress,json
from pathlib import Path
from urllib.parse import urlsplit
from dnfgm.config import Settings
p=Path('/etc/dnf-gm/config.json')
s=Settings(**json.loads(p.read_text())).check()
print(ipaddress.IPv4Address(s.db_host))
PY
)
# Install the fixed persistent admission gate automatically; do not leave this
# as a manual SSH feature switch. The helper verifies migration 013 first and
# preserves existing freezes, credentials and web capability choices.
/opt/dnf-gm/venv/bin/python "$BASE/deploy/configure_write_gate.py"
if [[ -L /opt/dnf-gm/current && "$(readlink -f /opt/dnf-gm/current)" != "$BASE" ]]; then
 ln -sfn "$(readlink -f /opt/dnf-gm/current)" /opt/dnf-gm/previous
fi
ln -sfn "$BASE" /opt/dnf-gm/.current-next
mv -Tf /opt/dnf-gm/.current-next /opt/dnf-gm/current
install -d -m 755 /var/lib/dnf-gm /etc/systemd/system/dnf-gm.service.d
if [[ -f "$BASE/catalog.sqlite" ]]; then install -m 444 "$BASE/catalog.sqlite" /var/lib/dnf-gm/catalog.sqlite; fi
install -m 644 "$BASE/deploy/dnf-gm.slice" "$BASE/deploy/dnf-gm.service" "$BASE/deploy/dnf-gm-monitor.service" /etc/systemd/system/
printf '[Service]\nIPAddressAllow=%s/32\n' "$DB_IP" > /etc/systemd/system/dnf-gm.service.d/database.conf
systemctl daemon-reload
systemctl enable dnf-gm-monitor.service dnf-gm.service
rm -f /run/dnf-gm/status.json
systemctl start dnf-gm-monitor.service
READY=false
for _ in $(seq 1 60); do
 if /opt/dnf-gm/venv/bin/python - <<'PY'
import json,time
try:
 import subprocess
 d=json.load(open('/run/dnf-gm/status.json'))
 pid=int(subprocess.check_output(['systemctl','show','dnf-gm-monitor.service','--property=MainPID','--value']))
 assert d.get('collector_pid')==pid and pid>0
 assert 0<=time.time()-d['collected_at']<45 and d['core_ok'] and d['mem_available_mib']>=256 and d['swap_free_mib']>=1536 and d['disk_free_gib']>=2
except Exception:raise SystemExit(1)
PY
 then READY=true; break; fi
 sleep 2
done
[[ "$READY" == true ]] || { echo 'Monitor not healthy; application remains stopped' >&2; exit 1; }
systemctl start dnf-gm.service
HOST=$(/opt/dnf-gm/venv/bin/python - <<'PY'
import json
from urllib.parse import urlsplit
print(urlsplit(json.load(open('/etc/dnf-gm/config.json'))['origins'][0]).netloc)
PY
)
for _ in $(seq 1 20); do
 if curl --noproxy '*' -fsS --max-time 5 -H "Host: $HOST" http://127.0.0.1:8765/dnf-gm/api/v1/ready >/dev/null; then
  if [[ "$RECOVERY_INHIBIT_OWNED" == true ]]; then rm -f /var/lib/dnf-gm/no-auto-recover; fi
  if [[ "$CLEANUP_RESTART" == true && -f "$BASE/deploy/dnf-gm-cleanup.service" ]]; then
   install -m 644 "$BASE/deploy/dnf-gm-cleanup.service" "$BASE/deploy/dnf-gm-cleanup.timer" /etc/systemd/system/
   systemctl daemon-reload
   systemctl start dnf-gm-cleanup.timer
  fi
  echo 'GM loopback ready. Nginx was not changed.'
  exit 0
 fi
 sleep 2
done
systemctl stop dnf-gm.service
echo 'Health failed; GM stopped. Review logs and roll back explicitly.' >&2
exit 1
