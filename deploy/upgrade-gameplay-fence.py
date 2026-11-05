"""Install management-only transaction fence and minimum locking-read grant.

No game writes, service restart, gate initialization or permission-policy change.
Run as part of a reviewed release upgrade, never as a way to reopen maintenance.
"""
import argparse
import json
import os
from pathlib import Path
import re

from grants import gameplay_fence_sql
from provision import mysql
from check_maintenance_idle import assert_idle, assert_config_gate
from dnfgm.release_files import maintenance_lock


def upgrade_sql(user):
    return (Path(__file__).resolve().parents[1]/'migrations/013-gameplay-fence.sql').read_text()+(Path(__file__).resolve().parents[1]/'migrations/014-operation-outcomes.sql').read_text()+gameplay_fence_sql(user)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container',required=True)
    p.add_argument('--mysql-port',type=int,default=4000)
    p.add_argument('--db-account-host',required=True)
    a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root required')
    cfg=json.loads(Path('/etc/dnf-gm/config.json').read_text());name=cfg['db_user']
    if (not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or name.lower() in ('root','game')
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}',a.db_account_host)
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}',a.container)
            or not 1<=a.mysql_port<=65535):raise SystemExit('Invalid maintenance target')
    with maintenance_lock(Path('/var/lib/dnf-gm/maintenance.lock')):
        assert_idle()
        assert_config_gate()
        mysql(a.container,a.mysql_port,upgrade_sql(f"'{name}'@'{a.db_account_host}'"))
    print('013/014 management transaction fence and outcome index and SELECT grant installed. No game rows, services or owner switches changed.')


if __name__=='__main__':main()
