"""Add only reviewed lock-archive column grants. Never activates game writes."""
import argparse
import json
import os
from pathlib import Path
import re

from grants import equipment_unlock_sql
from provision import mysql


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container', required=True)
    p.add_argument('--mysql-port', type=int, default=4000)
    p.add_argument('--db-account-host', required=True)
    a = p.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    cfg = json.loads(Path('/etc/dnf-gm/config.json').read_text())
    name = cfg['db_user']
    if (not re.fullmatch(r'[A-Za-z0-9_]{1,32}', name) or name.lower() in ('root', 'game')
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}', a.db_account_host)
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', a.container)
            or not 1 <= a.mysql_port <= 65535):
        raise SystemExit('Invalid maintenance target')
    mysql(a.container, a.mysql_port, equipment_unlock_sql(f"'{name}'@'{a.db_account_host}'"))
    print('Lock archive column grants applied. Writes remain explicitly configured.')


if __name__ == '__main__':
    main()
