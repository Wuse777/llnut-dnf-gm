"""Install inventory management tables; storage UPDATE grants are explicit opt-in."""
import argparse
import json
import os
from pathlib import Path
import re
from grants import inventory_management_sql,inventory_storage_sql
from provision import mysql


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container',required=True);p.add_argument('--mysql-port',type=int,default=4000)
    p.add_argument('--db-account-host',required=True)
    p.add_argument('--enable-storage-writes',action='store_true')
    p.add_argument('--acknowledge-maintenance-protocol',action='store_true')
    a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root required')
    cfg=json.loads(Path('/etc/dnf-gm/config.json').read_text());name=cfg['db_user']
    if (not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or name.lower() in ('root','game')
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}',a.db_account_host)
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}',a.container) or not 1<=a.mysql_port<=65535):
        raise SystemExit('Invalid maintenance target')
    if a.enable_storage_writes and not a.acknowledge_maintenance_protocol:
        raise SystemExit('Storage grants require explicit reviewed maintenance protocol acknowledgement')
    user=f"'{name}'@'{a.db_account_host}'"
    sql=(Path(__file__).resolve().parents[1]/'migrations/009-inventory-operations.sql').read_text()+inventory_management_sql(user)
    if a.enable_storage_writes:sql+=inventory_storage_sql(user)
    mysql(a.container,a.mysql_port,sql)
    print('Inventory migration applied. Application write switches unchanged; no game data or services modified.')


if __name__=='__main__':main()
