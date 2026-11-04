"""Add durable scheduling management tables only. No game writes or service restarts."""
import argparse
import json
import os
from pathlib import Path
import re
from grants import schedules_sql
from provision import mysql


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container',required=True)
    parser.add_argument('--mysql-port',type=int,default=4000)
    parser.add_argument('--db-account-host',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise SystemExit('Root required')
    config=json.loads(Path('/etc/dnf-gm/config.json').read_text())
    name=config['db_user']
    if (not re.fullmatch(r'[A-Za-z0-9_]{1,32}',name) or name.lower() in ('root','game')
        or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}',args.db_account_host)
        or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}',args.container)
        or not 1<=args.mysql_port<=65535):
        raise SystemExit('Invalid maintenance target')
    migration=(Path(__file__).resolve().parents[1]/'migrations/008-schedules.sql').read_text()
    mysql(args.container,args.mysql_port,migration+'\n'+schedules_sql(f"'{name}'@'{args.db_account_host}'"))
    print('Scheduling migration and grants applied. Scheduling remains unchanged; no rewards or announcements sent.')


if __name__=='__main__':
    main()
