"""Install web-managed owner capabilities and initialize all implemented switches."""
import argparse
import json
import os
from pathlib import Path
import re
from grants import capability_policy_sql, inventory_storage_sql, initialize_owner_capabilities_sql
from provision import mysql


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container',required=True);p.add_argument('--mysql-port',type=int,default=4000)
    p.add_argument('--db-account-host',required=True)
    a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root required')
    cfg=json.loads(Path('/etc/dnf-gm/config.json').read_text());name=cfg['db_user']
    if (not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or name.lower() in ('root','game')
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}',a.db_account_host)
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}',a.container) or not 1<=a.mysql_port<=65535):
        raise SystemExit('Invalid maintenance target')
    user=f"'{name}'@'{a.db_account_host}'"
    sql=(Path(__file__).resolve().parents[1]/'migrations/012-capabilities.sql').read_text()+capability_policy_sql(user)+inventory_storage_sql(user)+initialize_owner_capabilities_sql()
    mysql(a.container,a.mysql_port,sql)
    print('Owner web capabilities initialized (existing choices preserved). Required inventory column grants installed. No game rows or services modified.')


if __name__=='__main__':main()
